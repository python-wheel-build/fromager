import functools
import json
import logging
import os

import requests

logger = logging.getLogger(__name__)
_trigger_url = 'https://gitlab.com/api/v4/projects/56921574/trigger/pipeline'


def build_cli(parser, subparsers):
    parser_job = subparsers.add_parser('job')
    job_subparsers = parser_job.add_subparsers(title='pipeline jobs', dest='command')

    parser_job_bootstrap = job_subparsers.add_parser('bootstrap')
    parser_job_bootstrap.set_defaults(func=do_job_bootstrap)
    parser_job_bootstrap.add_argument('dist_name')
    parser_job_bootstrap.add_argument('dist_version')
    parser_job_bootstrap.add_argument('--python', '-p', default='python3.11')

    parser_job_build_wheel = job_subparsers.add_parser('build-wheel')
    parser_job_build_wheel.set_defaults(func=do_job_build_wheel)
    parser_job_build_wheel.add_argument('dist_name')
    parser_job_build_wheel.add_argument('dist_version')
    parser_job_build_wheel.add_argument('--python', '-p', default='python3.11')


def requires_token(f):
    "Decorate f() so that it receives the GITLAB_TOKEN as the second argument."
    @functools.wraps(f)
    def provides_token(args):
        token = os.environ.get('GITLAB_TOKEN')
        if not token:
            raise ValueError('Please set the GITLAB_TOKEN environment variable')
        return f(args, token)
    return provides_token


@requires_token
def do_job_bootstrap(args, token):
    run_job(
        'bootstrap',
        token,
        variables={
            'PYTHON': args.python,
            'DIST_NAME': args.dist_name,
            'DIST_VERSION': args.dist_version,
        })


@requires_token
def do_job_build_wheel(args, token):
    run_job(
        'build-wheel',
        token,
        variables={
            'PYTHON': args.python,
            'DIST_NAME': args.dist_name,
            'DIST_VERSION': args.dist_version,
        })


def run_job(job_name, token, variables):
    data = {
        'token': token,
        'ref': 'main',
        'variables[JOB]': job_name,
    }
    for n, v in variables.items():
        data[f'variables[{n}]'] = v
    r = requests.post(_trigger_url, data=data)
    output = r.json()
    print(json.dumps(output, sort_keys=True, indent=2))
