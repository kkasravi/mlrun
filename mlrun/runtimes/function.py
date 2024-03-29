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

import json
import requests
from datetime import datetime
import asyncio
from aiohttp.client import ClientSession
import logging
from sys import stdout

from .base import MLRuntime
from ..utils import update_in
from ..collections import RunList

from nuclio_sdk import Context as _Context, Logger
from nuclio_sdk.logger import HumanReadableFormatter
from nuclio_sdk import Event


class RemoteRuntime(MLRuntime):
    kind = 'remote'

    def _run(self, struct):
        if self._secrets:
            update_in(struct, 'spec.secret_sources',
                      self._secrets.to_serial())
        log_level = self.execution.log_level
        headers = {'x-nuclio-log-level': log_level}
        try:
            resp = requests.put(self.command, json=struct, headers=headers)
        except OSError as err:
            print('ERROR: %s', str(err))
            raise OSError('error: cannot run function at url {}'.format(self.command))

        if not resp.ok:
            print('bad resp!!\n', resp.text)
            return None

        logs = resp.headers.get('X-Nuclio-Logs')
        if logs:
            print(parse_logs(logs))

        return resp.json()

    def _run_many(self, tasks):
        secrets = self._secrets.to_serial() if self._secrets else None
        log_level = self.execution.log_level
        headers = {'x-nuclio-log-level': log_level}

        loop = asyncio.get_event_loop()
        future = asyncio.ensure_future(
            invoke_async(tasks, self.command, headers, secrets))

        loop.run_until_complete(future)
        return future.result()


def parse_logs(logs):
    logs = json.loads(logs)
    lines = ''
    for line in logs:
        extra = []
        for k, v in line.items():
            if k not in ['time', 'level', 'name', 'message']:
                extra.append('{}={}'.format(k, v))
        line['extra'] = ', '.join(extra)
        line['time'] = datetime.fromtimestamp(float(line['time'])/1000).strftime('%Y-%m-%d %H:%M:%S.%f')
        lines += '{time}  {level:<6} {message}  {extra}\n'.format(**line)

    return lines


async def submit(session, url, body, headers=None):
    async with session.put(url, json=body, headers=headers) as response:
        text = await response.text()
        logs = response.headers.get('X-Nuclio-Logs', None)
        return response.status, text, logs


async def invoke_async(runs, url, headers, secrets):
    results = RunList()
    tasks = []

    async with ClientSession() as session:
        for run in runs:
            update_in(run, 'spec.secret_sources', secrets)
            tasks.append(asyncio.ensure_future(
                submit(session, url, run, headers),
            ))

        for status, resp, logs in await asyncio.gather(*tasks):

            if status != 200:
                print("failed to access {} - {}".format(url, resp))
            else:
                results.append(json.loads(resp))

            if logs:
                parsed = parse_logs(logs)
                if parsed:
                    print(parsed, '----------')

    return results


def fake_nuclio_context(body, headers=None):

    class FunctionContext(_Context):
        """Wrapper around nuclio_sdk.Context to make automatically create
        logger"""

        def __getattribute__(self, attr):
            value = object.__getattribute__(self, attr)
            if value is None and attr == 'logger':
                value = self.logger = Logger(level=logging.INFO)
                value.set_handler(
                    'mlrun', stdout, HumanReadableFormatter())
            return value

        def set_logger_level(self, verbose=False):
            if verbose:
                level = logging.DEBUG
            else:
                level = logging.INFO
            value = self.logger = Logger(level=level)
            value.set_handler('mlrun', stdout, HumanReadableFormatter())

    return FunctionContext(), Event(body=body, headers=headers)


