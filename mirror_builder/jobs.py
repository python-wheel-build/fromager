import functools
import json
import logging
import os
import time

import gitlab

logger = logging.getLogger(__name__)

_project_id = 56921574


def build_cli(parser, subparsers):
    parser_job = subparsers.add_parser('job')
    job_subparsers = parser_job.add_subparsers(title='pipeline jobs', dest='command')

    parser_job_bootstrap = job_subparsers.add_parser('bootstrap')
    parser_job_bootstrap.set_defaults(func=do_job_bootstrap)
    parser_job_bootstrap.add_argument('dist_name')
    parser_job_bootstrap.add_argument('dist_version')
    parser_job_bootstrap.add_argument('--python', '-p', default='python3.11')
    parser_job_bootstrap.add_argument('--wait', '-w', default=False, action='store_true')
    parser_job_bootstrap.add_argument('--show-progress', default=False, action='store_true')

    parser_job_onboard_sdist = job_subparsers.add_parser('onboard-sdist')
    parser_job_onboard_sdist.set_defaults(func=do_job_onboard_sdist)
    parser_job_onboard_sdist.add_argument('dist_name')
    parser_job_onboard_sdist.add_argument('dist_version')
    parser_job_onboard_sdist.add_argument('--wait', '-w', default=False, action='store_true')
    parser_job_onboard_sdist.add_argument('--show-progress', default=False, action='store_true')

    parser_job_onboard_sequence = job_subparsers.add_parser('onboard-sequence')
    parser_job_onboard_sequence.set_defaults(func=do_job_onboard_sequence)
    parser_job_onboard_sequence.add_argument('build_order_file')
    parser_job_onboard_sequence.add_argument('--show-progress', default=False, action='store_true')

    parser_job_build_wheel = job_subparsers.add_parser('build-wheel')
    parser_job_build_wheel.set_defaults(func=do_job_build_wheel)
    parser_job_build_wheel.add_argument('dist_name')
    parser_job_build_wheel.add_argument('dist_version')
    parser_job_build_wheel.add_argument('--python', '-p', default='python3.11')
    parser_job_build_wheel.add_argument('--wait', '-w', default=False, action='store_true')
    parser_job_build_wheel.add_argument('--show-progress', default=False, action='store_true')

    parser_job_build_sequence = job_subparsers.add_parser('build-sequence')
    parser_job_build_sequence.set_defaults(func=do_job_build_sequence)
    parser_job_build_sequence.add_argument('build_order_file')
    parser_job_build_sequence.add_argument('--python', '-p', default='python3.11')
    parser_job_build_sequence.add_argument('--show-progress', default=False, action='store_true')


def requires_client(f):
    "Decorate f() so that it receives the gitlab client as the second argument."
    @functools.wraps(f)
    def provides_client(args):
        token = os.environ.get('GITLAB_TOKEN')
        if not token:
            raise ValueError('Please set the GITLAB_TOKEN environment variable')
        client = gitlab.Gitlab(private_token=token)
        client.auth()
        return f(args, client)
    return provides_client


@requires_client
def do_job_bootstrap(args, client):
    run_pipeline(
        client,
        'bootstrap',
        variables={
            'PYTHON': args.python,
            'DIST_NAME': args.dist_name,
            'DIST_VERSION': args.dist_version,
        },
        wait=args.wait,
        show_progress=args.show_progress,
    )


@requires_client
def do_job_onboard_sdist(args, client):
    run_pipeline(
        client,
        'onboard-sdist',
        variables={
            'DIST_NAME': args.dist_name,
            'DIST_VERSION': args.dist_version,
        },
        wait=args.wait,
        show_progress=args.show_progress,
    )


@requires_client
def do_job_onboard_sequence(args, client):
    with open(args.build_order_file, 'r') as f:
        build_order = json.load(f)

    for step in build_order:
        dist = step['dist']
        version = step['version']
        print(f'{dist} {version}')

        run_pipeline(
            client,
            'onboard-sdist',
            variables={
                'DIST_NAME': dist,
                'DIST_VERSION': version,
            },
            wait=True,
            show_progress=args.show_progress,
        )


@requires_client
def do_job_build_wheel(args, client):
    run_pipeline(
        client,
        'build-wheel',
        variables={
            'PYTHON': args.python,
            'DIST_NAME': args.dist_name,
            'DIST_VERSION': args.dist_version,
        },
        wait=args.wait,
        show_progress=args.show_progress,
    )


@requires_client
def do_job_build_sequence(args, client):
    with open(args.build_order_file, 'r') as f:
        build_order = json.load(f)

    for step in build_order:
        dist = step['dist']
        version = step['version']
        print(f'{dist} {version}')

        run_pipeline(
            client,
            'build-wheel',
            variables={
                'PYTHON': args.python,
                'DIST_NAME': dist,
                'DIST_VERSION': version,
            },
            wait=True,
            show_progress=args.show_progress,
        )


def run_pipeline(client, job_name, variables, wait=False, show_progress=False):
    project = client.projects.get(_project_id)
    trigger = get_or_create_trigger(project, 'sequence-trigger')
    data = {}
    data.update(variables)
    data['JOB'] = job_name
    pipeline = project.trigger_pipeline(
        ref='main',
        token=trigger.token,
        variables=data,
    )
    print(f'pipeline: {pipeline.id} {pipeline.web_url}')
    if not wait:
        return
    while not pipeline.finished_at:
        if show_progress:
            print('.', end='', flush=True)
        pipeline.refresh()
        time.sleep(15)
    if show_progress:
        print()
    if pipeline.status != 'success':
        raise RuntimeError(f'Pipeline {pipeline.id} ended with status {pipeline.status} {pipeline.web_url}')


# https://python-gitlab.readthedocs.io/en/stable/gl_objects/pipelines_and_jobs.html
def get_or_create_trigger(project, trigger_description):
    for t in project.triggers.list():
        if t.description == trigger_description:
            return t
    return project.triggers.create({'description': trigger_description})
