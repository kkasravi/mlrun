# for this function to run in nuclio you need to:
# - set the python base image e.g.:
#     python:3.6-jessie
# - add mlrun package install to the Build commands:
#     pip install git+https://github.com/v3io/mlrun.git


from mlrun import get_or_create_ctx
import time

def handler(context, event):
    ctx = get_or_create_ctx('myfunc', event=event)
    p1 = ctx.get_param('p1', 1)
    p2 = ctx.get_param('p2', 'a-string')

    context.logger.info(
        f'Run: {ctx.name} uid={ctx.uid}:{ctx.iteration} Params: p1={p1}, p2={p2}')

    time.sleep(1)

    # log scalar values (KFP metrics)
    ctx.log_result('accuracy', p1 * 2)
    ctx.log_result('latency', p1 * 3)

    # log various types of artifacts (and set UI viewers)
    ctx.log_artifact('test.txt', body=b'abc is 123')
    ctx.log_artifact('test.html', body=b'<b> Some HTML <b>', viewer='web-app')

    context.logger.info('run complete!')
    return ctx.to_json()