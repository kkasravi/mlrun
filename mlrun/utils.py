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
import logging
from os import path
from sys import stdout
import yaml

yaml.Dumper.ignore_aliases = lambda *args : True


def create_logger():
    handler = logging.StreamHandler(stdout)
    handler.setFormatter(
        logging.Formatter('[%(name)s] %(asctime)s %(message)s'))
    logger = logging.getLogger('mlrun')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


logger = create_logger()
missing = object()

is_ipython = False
try:
    import IPython
    ipy = IPython.get_ipython()
    if ipy:
        is_ipython = True
except ImportError:
    pass

if is_ipython:
    # bypass Jupyter asyncio bug
    import nest_asyncio
    nest_asyncio.apply()


class run_keys:
    input_path = 'default_input_path'
    output_path = 'default_output_path'
    input_objects = 'input_objects'
    output_artifacts = 'output_artifacts'
    data_stores = 'data_stores'
    secrets = 'secret_sources'


def get_in(obj, keys, default=None):
    """
    >>> get_in({'a': {'b': 1}}, 'a.b')
    1
    """
    if isinstance(keys, str):
        keys = keys.split('.')

    for key in keys:
        if not obj or key not in obj:
            return default
        obj = obj[key]
    return obj


def update_in(obj, key, value, append=False, replace=True):
    parts = key.split('.') if isinstance(key, str) else key
    for part in parts[:-1]:
        sub = obj.get(part, missing)
        if sub is missing:
            sub = obj[part] = {}
        obj = sub

    last_key = parts[-1]
    if last_key not in obj:
        if append:
            obj[last_key] = []
        else:
            obj[last_key] = {}

    if append:
        if isinstance(value, list):
            obj[last_key] += value
        else:
            obj[last_key].append(value)
    else:
        if replace or not obj.get(last_key):
            obj[last_key] = value


def match_labels(labels, conditions):
    match = True

    def splitter(verb, text):
        items = text.split(verb)
        if len(items) != 2:
            raise ValueError('illegal condition - {}'.format(text))
        return labels.get(items[0].strip(), ''), items[1].strip()

    for condition in conditions:
        if '~=' in condition:
            l, val = splitter('~=', condition)
            match = match and val in l
        elif '!=' in condition:
            l, val = splitter('!=', condition)
            match = match and val != l
        elif '=' in condition:
            l, val = splitter('=', condition)
            match = match and val == l
        else:
            match = match and (labels.get(condition.strip(), '') != '')
    return match


def flatten(df, col, prefix=''):
    params = []
    for r in df[col]:
        if r:
            for k in r.keys():
                if k not in params:
                    params += [k]
    params
    for p in params:
        df[prefix + p] = df[col].apply(lambda x: x.get(p, '') if x else '')
    df.drop(col, axis=1, inplace=True)
    return df


def list2dict(lines: list):
    out = {}
    for line in lines:
        i = line.find('=')
        if i == -1:
            continue
        key, value = line[:i].strip(), line[i + 1:].strip()
        if key is None:
            raise ValueError('cannot find key in line (key=value)')
        value = path.expandvars(value)
        out[key] = value
    return out


def dict_to_list(struct: dict):
    if not struct:
        return []
    return [f'{k}={v}' for k, v in struct.items()]


def dict_to_yaml(struct):
    return yaml.dump(struct, default_flow_style=False,
                     sort_keys=False)


def uxjoin(base, path):
    if base:
        if not base.endswith('/'):
            base += '/'
        return '{}{}'.format(base, path)
    return path


class ModelObj:
    _dict_fields = []

    def to_dict(self, fields=None):
        struct = {}
        fields = fields or self._dict_fields
        for t in fields:
            val = getattr(self, t, None)
            if val is not None:
                if hasattr(val, 'to_dict'):
                    struct[t] = val.to_dict()
                else:
                    struct[t] = val
        return struct

    #@classmethod
    #def from_dict(cls, struct={}):
    #    for key, val in struct.items():

    def to_yaml(self):
        return dict_to_yaml(self.to_dict())

    def to_json(self):
        return json.dumps(self.to_dict())


def gen_md_table(header, rows=[]):

    def gen_list(items=[]):
        out = '|'
        for i in items:
            out += f' {i} |'
        return out

    out = gen_list(header) + '\n' + gen_list(len(header) * ['---']) + '\n'
    for r in rows:
        out += gen_list(r) + '\n'
    return out


def gen_html_table(header, rows=[]):

    style = '''    
<style type="text/css">
.tg  {border-collapse:collapse;border-spacing:0;}
.tg td{border-style:solid;border-width:1px;padding:6px 4px;}
.tg th{font-weight:normal;border-style:solid;border-width:1px;padding:6px 4px;}
</style>
'''

    def gen_list(items=[], tag='td'):
        out = ''
        for item in items:
            out += f'<{tag}>{item}</{tag}>'
        return out

    out = '<tr>' + gen_list(header, 'th') + '</tr>\n'
    for r in rows:
        out += '<tr>' + gen_list(r, 'td') + '</tr>\n'
    return style + '<table class="tg">\n' + out + '</table>\n\n'
