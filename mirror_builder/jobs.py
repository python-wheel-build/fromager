import functools
import json
import logging
import os
import time
from concurrent import futures

import gitlab
import resolvelib.resolvers
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from . import sources

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
    parser_job_bootstrap.add_argument('--output', '-o')

    parser_job_onboard_sdist = job_subparsers.add_parser('onboard-sdist')
    parser_job_onboard_sdist.set_defaults(func=do_job_onboard_sdist)
    parser_job_onboard_sdist.add_argument('dist_name')
    parser_job_onboard_sdist.add_argument('dist_version')
    parser_job_onboard_sdist.add_argument('--wait', '-w', default=False, action='store_true')
    parser_job_onboard_sdist.add_argument('--show-progress', default=False, action='store_true')
    parser_job_onboard_sdist.add_argument('--force', default=False, action='store_true')

    parser_job_onboard_sequence = job_subparsers.add_parser('onboard-sequence')
    parser_job_onboard_sequence.set_defaults(func=do_job_onboard_sequence)
    parser_job_onboard_sequence.add_argument('build_order_file')
    parser_job_onboard_sequence.add_argument('--force', default=False, action='store_true')

    parser_job_build_wheel = job_subparsers.add_parser('build-wheel')
    parser_job_build_wheel.set_defaults(func=do_job_build_wheel)
    parser_job_build_wheel.add_argument('dist_name')
    parser_job_build_wheel.add_argument('dist_version')
    parser_job_build_wheel.add_argument('--wait', '-w', default=False, action='store_true')
    parser_job_build_wheel.add_argument('--show-progress', default=False, action='store_true')
    parser_job_build_wheel.add_argument('--force', default=False, action='store_true')

    parser_job_build_sequence = job_subparsers.add_parser('build-sequence')
    parser_job_build_sequence.set_defaults(func=do_job_build_sequence)
    parser_job_build_sequence.add_argument('build_order_file')
    parser_job_build_sequence.add_argument('--show-progress', default=False, action='store_true')
    parser_job_build_sequence.add_argument('--force', default=False, action='store_true')

    parser_job_update_tools = job_subparsers.add_parser('update-tools')
    parser_job_update_tools.set_defaults(func=do_job_update_tools)
    parser_job_update_tools.add_argument('--wait', '-w', default=False, action='store_true')
    parser_job_update_tools.add_argument('--show-progress', default=False, action='store_true')


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
    dist_name = canonicalize_name(args.dist_name)
    pipeline = run_pipeline(
        client,
        f'bootstrap {dist_name} {args.dist_version}',
        'bootstrap',
        variables={
            'PYTHON': args.python,
            'DIST_NAME': dist_name,
            'DIST_VERSION': args.dist_version,
        },
        wait=args.wait or args.output,
        show_progress=args.show_progress,
    )
    if args.wait or args.output:
        project = client.projects.get(_project_id)
        for ijob in pipeline.jobs.list():
            # The iterator gives us a partial job that can't download
            # artifacts, so get a real object.
            job = project.jobs.get(ijob.id)
            build_order = job.artifact('work-dir/build-order.json').decode('utf-8')
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(build_order)
                print(f'wrote {args.output}')
            else:
                print(build_order)


def _sdist_exists(dist_name, dist_version):
    req = Requirement(f'{dist_name}=={dist_version}')
    try:
        url, _ = sources.resolve_sdist(
            req,
            'https://pyai.fedorainfracloud.org/experimental/sources/+simple/',
            only_sdists=True,
        )
    except resolvelib.resolvers.ResolutionImpossible:
        return False
    return bool(url)


@requires_client
def do_job_onboard_sdist(args, client):
    dist_name = canonicalize_name(args.dist_name)
    if not args.force and _sdist_exists(dist_name, args.dist_version):
        print(f'already have a source archive for {dist_name} {args.dist_version}')
        return
    run_pipeline(
        client,
        f'onboard-sdist {dist_name} {args.dist_version}',
        'onboard-sdist',
        variables={
            'DIST_NAME': dist_name,
            'DIST_VERSION': args.dist_version,
        },
        wait=args.wait,
        show_progress=args.show_progress,
    )


@requires_client
def do_job_onboard_sequence(args, client):
    with open(args.build_order_file, 'r') as f:
        build_order = json.load(f)

    def run_one(step):
        try:
            dist = canonicalize_name(step['dist'])
            version = step['version']
            if not args.force and _sdist_exists(dist, version):
                print(f'already have a source archive for {dist} {version}', flush=True)
                return
            run_pipeline(
                client,
                f'onboard-sdist {dist} {version}',
                'onboard-sdist',
                variables={
                    'DIST_NAME': dist,
                    'DIST_VERSION': version,
                },
                # Always wait to help enforce concurrency limits.
                wait=True,
                # Don't show dots, only start and stop messages
                show_progress=False,
            )
        except Exception as err:
            raise RuntimeError(f'failed to onboard {dist} {version}: {err}') from err

    executor = futures.ThreadPoolExecutor(max_workers=3)
    for result in executor.map(run_one, build_order):
        if result:
            print(result)


def _wheel_exists(dist_name, dist_version):
    req = Requirement(f'{dist_name}=={dist_version}')
    try:
        url, _ = sources.resolve_sdist(
            req,
            'https://pyai.fedorainfracloud.org/experimental/cpu/+simple/',
            only_sdists=False,
        )
    except resolvelib.resolvers.ResolutionImpossible:
        return False
    return bool(url)


@requires_client
def do_job_build_wheel(args, client):
    dist_name = canonicalize_name(args.dist_name)
    if not args.force and _wheel_exists(dist_name, args.dist_version):
        print(f'already have a wheel for {dist_name} {args.dist_version}')
        return
    run_pipeline(
        client,
        f'build-wheel {dist_name} {args.dist_version}',
        'build-wheel',
        variables={
            'DIST_NAME': dist_name,
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
        dist = canonicalize_name(step['dist'])
        version = step['version']

        if not args.force and _wheel_exists(dist, version):
            print(f'already have a wheel for {dist} {version}')
            continue

        run_pipeline(
            client,
            f'build-wheel {dist} {version}',
            'build-wheel',
            variables={
                'DIST_NAME': dist,
                'DIST_VERSION': version,
            },
            wait=True,
            show_progress=args.show_progress,
        )


@requires_client
def do_job_update_tools(args, client):
    run_pipeline(
        client,
        'update-tools',
        'update-tools',
        variables={},
        wait=args.wait,
        show_progress=args.show_progress,
    )


def run_pipeline(client, title, job_name, variables, wait=False, show_progress=False):
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
    print(f'starting {title} pipeline: {pipeline.id} {pipeline.web_url}')
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
    print(f'finished {title}')
    return pipeline


# https://python-gitlab.readthedocs.io/en/stable/gl_objects/pipelines_and_jobs.html
def get_or_create_trigger(project, trigger_description):
    for t in project.triggers.list():
        if t.description == trigger_description:
            return t
    return project.triggers.create({'description': trigger_description})
