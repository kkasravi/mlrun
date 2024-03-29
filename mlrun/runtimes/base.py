# Copyright 2018 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import socket
import uuid
from datetime import datetime
import json
import getpass
from copy import deepcopy
from os import environ
import pandas as pd
from io import StringIO

from ..db import get_run_db
from ..secrets import SecretsStore
from ..utils import (run_keys, gen_md_table, dict_to_yaml, get_in,
                     update_in, logger, is_ipython)
from ..execution import MLClientCtx
from ..artifacts import TableArtifact
from ..collections import RunList
from .generators import GridGenerator, ListGenerator


class RunError(Exception):
    pass


KFPMETA_DIR = environ.get('KFPMETA_OUT_DIR', '/')


class MLRuntime:
    kind = ''

    def __init__(self, command='', args=[], handler=None):
        self.struct = None
        self.command = command
        self.args = args
        self.handler = handler
        self.rundb = ''
        self.db_conn = None
        self.task_generator = None
        self._secrets = None
        self.secret_sources = None
        self.with_kfp = False
        self.execution = None #MLClientCtx()

    def process_struct(self, struct, rundb='',
                       hyperparams=None, param_file=None):

        self.command = get_in(struct, 'spec.runtime.command')
        self.args = get_in(struct, 'spec.runtime.args', [])
        self.secret_sources = get_in(struct, ['spec', run_keys.secrets])
        if self.secret_sources:
            self._secrets = SecretsStore.from_dict(struct)

        if not get_in(struct, 'metadata.uid'):
            update_in(struct, 'metadata.uid', uuid.uuid4().hex)

        rundb = rundb or environ.get('MLRUN_META_DBPATH', '')
        if rundb:
            self.rundb = rundb
            self.db_conn = get_run_db(rundb).connect(self._secrets)

        labels = get_in(struct, 'metadata.labels', {})
        set_if_none(labels, 'owner', getpass.getuser())
        set_if_none(labels, 'host', socket.gethostname())
        set_if_none(labels, 'runtime', self.kind)
        add_code_metadata(labels)
        update_in(struct, 'metadata.labels', labels)
        self.struct = struct

        self.execution = MLClientCtx.from_dict(struct, self.db_conn)

        if hyperparams:
            self.task_generator = GridGenerator(hyperparams)
        elif param_file:
            obj = self.execution.get_object('param_file.csv', param_file)
            self.task_generator = ListGenerator(obj.get())

    def run(self):
        def show(results, resp):
            results.append(resp)
            if is_ipython:
                results.show()
            return resp

        if self.task_generator:
            generator = self.task_generator.generate(self.struct)
            results = self._run_many(generator)
            self.results_to_iter(results)
            resp = self.execution.to_dict()
            if resp and self.with_kfp:
                self.write_kfpmeta(resp)
            return show(results, resp)
        else:
            results = RunList()
            try:
                resp = self._run(self.struct)
                if resp and self.with_kfp:
                    self.write_kfpmeta(resp)
                return show(results, self._post_run(resp))
            except RunError as err:
                logger.error(f'run error - {err}')
                self.execution.set_state(error=err)
                return show(results, self.execution.to_dict())

    def _run(self, struct):
        pass

    def _run_many(self, tasks):
        results = RunList()
        for task in tasks:
            try:
                resp = self._run(task)
                resp = self._post_run(resp)
            except RunError as err:
                task['status']['state'] = 'error'
                task['status']['error'] = err
                resp = self._post_run(task)
            results.append(resp)
        return results

    def _post_run(self, resp):
        if not resp:
            return {}

        if isinstance(resp, str):
            resp = json.loads(resp)

        update_in(resp, ['status', 'last_update'], str(datetime.now()))
        if get_in(resp, ['status', 'state'], '') != 'error':
            resp['status']['state'] = 'completed'
        self._save_run(resp)
        return resp

    def _save_run(self, struct):
        if self.db_conn:
            project = self.execution.project
            uid = get_in(struct, 'metadata.uid')
            iter = get_in(struct, 'metadata.iteration')
            if iter:
                uid = f'{uid}-{iter}'
            self.db_conn.store_run(struct, uid, project, commit=True)
        return struct

    def results_to_iter(self, results):
        iter = []
        failed = 0
        for task in results:
            state = get_in(task, ['status', 'state'])
            id = get_in(task, ['metadata', 'iteration'])
            struct = {'param': get_in(task, ['spec', 'parameters'], {}),
                      'output': get_in(task, ['status', 'outputs'], {}),
                      'state': state,
                      'iter': id,
                      }
            if state == 'error':
                failed += 1
                logger.error(f'error in task  {self.execution.uid}:{id} - ' + get_in(task, ['status', 'error'], ''))
            elif state != 'completed':
                self._post_run(task)

            iter.append(struct)

        df = pd.io.json.json_normalize(iter).sort_values('iter')
        header = df.columns.values.tolist()
        results = [header] + df.values.tolist()
        self.execution.log_iteration_results(results)

        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False, line_terminator='\n', encoding='utf-8')
        self.execution.log_artifact(
            TableArtifact('iteration_results.csv',
                          body=csv_buffer.getvalue(),
                          header=header,
                          viewer='table'))
        if failed:
            self.execution.set_state(error=f'{failed} tasks failed, check logs for db for details')
        else:
            self.execution.set_state('completed')

    def _force_handler(self):
        if not self.handler:
            raise RunError('handler must be provided for {} runtime'.format(self.kind))

    def write_kfpmeta(self, struct):
        outputs = struct['status'].get('outputs', {})
        metrics = {'metrics':
                       [{'name': k,
                         'numberValue': v,
                         } for k, v in outputs.items() if isinstance(v, (int, float, complex))]}
        with open(KFPMETA_DIR + 'mlpipeline-metrics.json', 'w') as f:
            json.dump(metrics, f)

        output_artifacts = get_kfp_outputs(
            struct['status'].get(run_keys.output_artifacts, []))

        text = '# Run Report\n'
        if 'iterations' in struct['status']:
            iter = struct['status']['iterations']
            iter_html = gen_md_table(iter[0], iter[1:])
            text += '## Iterations\n' + iter_html
            struct = deepcopy(struct)
            del struct['status']['iterations']

        text += "## Metadata\n```yaml\n" + dict_to_yaml(struct) + "```\n"

        #with open('sum.md', 'w') as fp:
        #    fp.write(text)

        metadata = {
            'outputs': output_artifacts + [{
                'type': 'markdown',
                'storage': 'inline',
                'source': text
            }]
        }
        with open(KFPMETA_DIR + 'mlpipeline-ui-metadata.json', 'w') as f:
            json.dump(metadata, f)


def get_kfp_outputs(artifacts):
    outputs = []
    for output in artifacts:
        key = output["key"]
        target = output.get('target_path', '')
        target = output.get('inline', target)
        try:
            with open(f'/tmp/{key}', 'w') as fp:
                fp.write(target)
        except:
            pass

        if target.startswith('v3io:///'):
            target = target.replace('v3io:///', 'http://v3io-webapi:8081/')

        viewer = output.get('viewer', '')
        if viewer in ['web-app', 'chart']:
            meta = {'type': 'web-app',
                    'source': target}
            outputs += [meta]

        elif viewer == 'table':
            header = output.get('header', None)
            if header and target.endswith('.csv'):
                meta = {'type': 'table',
                        'format': 'csv',
                        'header': header,
                        'source': target}
                outputs += [meta]

    return outputs


def add_code_metadata(labels):
    dirpath = './'
    try:
        from git import Repo
        from git.exc import GitCommandError, InvalidGitRepositoryError
    except ImportError:
        return

    try:
        repo = Repo(dirpath, search_parent_directories=True)
        remotes = [remote.url for remote in repo.remotes]
        if len(remotes) > 0:
            set_if_none(labels, 'repo', remotes[0])
            set_if_none(labels, 'commit', repo.head.commit.hexsha)
    except (GitCommandError, InvalidGitRepositoryError):
        pass


def set_if_none(struct, key, value):
    if not struct.get(key):
        struct[key] = value