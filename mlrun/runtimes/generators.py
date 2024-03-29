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

from io import BytesIO
import pandas as pd
from copy import deepcopy
from ..utils import get_in, update_in


class TaskGenerator:
    def generate(self, struct):
        pass


class GridGenerator(TaskGenerator):
    def __init__(self, hyperparams):
        self.hyperparams = hyperparams

    def generate(self, struct):
        i = 0
        params = self.grid_to_list()
        max = len(next(iter(params.values())))

        while i < max:
            newstruct = deepcopy(struct)
            param_dict = get_in(newstruct, ['spec', 'parameters'], {})
            for key, values in params.items():
                param_dict[key] = values[i]
            update_in(newstruct, ['spec', 'parameters'], param_dict)
            update_in(newstruct, ['metadata', 'iteration'], i + 1)
            i += 1
            yield newstruct

    def grid_to_list(self):
        arr = {}
        lastlen = 1
        for pk, pv in self.hyperparams.items():
            for p in arr.keys():
                arr[p] = arr[p] * len(pv)
            expanded = []
            for i in range(len(pv)):
                expanded += [pv[i]] * lastlen
            arr[pk] = expanded
            lastlen = lastlen * len(pv)

        return arr


class ListGenerator(TaskGenerator):
    def __init__(self, body):

        self.df = pd.read_csv(BytesIO(body), encoding='utf-8')

    def generate(self, struct):
        i = 0
        for idx, row in self.df.iterrows():
            newstruct = deepcopy(struct)
            param_dict = get_in(newstruct, ['spec', 'parameters'], {})
            for key, values in row.to_dict().items():
                param_dict[key] = values
            update_in(newstruct, ['spec', 'parameters'], param_dict)
            update_in(newstruct, ['metadata', 'iteration'], i + 1)
            i += 1
            yield newstruct




