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

def xcp_op(src, dst, f='', recursive=False, mtime='', log_level='info', minsize=0, maxsize=0):
    """Parallel cloud copy."""
    from kfp import dsl
    args = [
        # '-f', f,
        # '-t', mtime,
        # '-m', maxsize,
        # '-n', minsize,
        # '-v', log_level,
        src, dst,
    ]
    if recursive:
        args = ['-r'] + args

    return dsl.ContainerOp(
        name='xcp',
        image='yhaviv/invoke',
        command=['xcp'],
        arguments=args,
    )


def mount_v3io(name='v3io', remote='~/', mount_path='/User', access_key=''):
    """
        Modifier function to apply to a Container Op to volume mount a v3io path
        Usage:
            train = train_op(...)
            train.apply(mount_v3io(container='users', sub_path='/iguazio', mount_path='/data'))
    """

    def _mount_v3io(task):
        from kubernetes import client as k8s_client
        from os import environ
        _access_key = access_key or environ.get('V3IO_ACCESS_KEY')
        _remote = remote

        if _remote.startswith('~/'):
            user = environ.get('V3IO_USERNAME', '')
            if not user:
                raise ValueError('user name/env must be specified when using "~" in path')
            if _remote == '~/':
                _remote = 'users/' + user
            else:
                _remote = 'users/' + user + _remote[1:]
        container, subpath = split_path(_remote)

        opts = {'accessKey': _access_key, 'container': container, 'subPath': subpath}
        vol = {'flexVolume': k8s_client.V1FlexVolumeSource('v3io/fuse', options=opts), 'name': name}

        task.add_volume(vol).add_volume_mount(k8s_client.V1VolumeMount(mount_path=mount_path, name=name))

        task = v3io_cred(access_key=access_key)(task)
        return (task)

    return _mount_v3io


def v3io_cred(api='', user='', access_key=''):
    """
        Modifier function to copy local v3io env vars to task
        Usage:
            train = train_op(...)
            train.apply(use_v3io_cred())
    """

    def _use_v3io_cred(task):
        from kubernetes import client as k8s_client
        from os import environ
        web_api = api or environ.get('V3IO_API')
        _user = environ.get('V3IO_USERNAME')
        _access_key = environ.get('V3IO_ACCESS_KEY')

        return (
            task
                .add_env_variable(k8s_client.V1EnvVar(name='V3IO_API', value=web_api))
                .add_env_variable(k8s_client.V1EnvVar(name='V3IO_USERNAME', value=_user))
                .add_env_variable(k8s_client.V1EnvVar(name='V3IO_ACCESS_KEY', value=_access_key))
        )

    return _use_v3io_cred


def split_path(mntpath=''):
    if mntpath[0] == '/':
        mntpath = mntpath[1:]
    paths = mntpath.split('/')
    container = paths[0]
    subpath = ''
    if len(paths) > 1:
        subpath = mntpath[len(container):]
    return container, subpath
