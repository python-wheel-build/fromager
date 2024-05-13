"""Build overrides for PyArrow

Settings are based on:

- https://arrow.apache.org/docs/dev/developers/python.html#using-system-and-bundled-dependencies
- https://src.fedoraproject.org/rpms/libarrow/blob/rawhide/f/libarrow.spec

Note that we're downloading a PyArrow tarball created from a tag (not
a release). It is not strictly an sdist. Instead it's an archive of
the git repo at that tag point for *ALL* of the Arrow project. We
build the whole thing to get the wheel with all of the matching libs
included.

The upstream instructions want to use `python setup.py bdist_wheel`
but that front-end doesn't support options we need for build
isolation, so instead we set some extra environment variables to pass
equivalent settings to `pip wheel`.

The CUDA-related options are handled directly here instead of
providing an environment override file because in addition to setting
an environment variable for the wheel build we have to pass a command
line option to cmake for the initial library build.

"""

import logging
import os
import platform
import tempfile

from mirror_builder import dependencies, external_commands, sources

logger = logging.getLogger(__name__)


def download_source(ctx, req, sdist_server_url):
    # # Downloading source from upstream is the special case
    # if "pypi.org" not in sdist_server_url:
    #     return sources.default_download_source(ctx, req, sdist_server_url)

    # FIXME: Always looks at PyPI. What do we do about publishing sdists?
    _, version = sources.resolve_sdist(req, sources.PYPI_SERVER_URL, only_sdists=True)
    logger.info(f"resolved {req} to {version}")
    source_filename = sources.download_url(
        ctx.sdists_downloads,
        _get_pyarrow_release_tarball_url(version),
    )
    logger.info('have source for %s version %s in %s', req, version, source_filename)
    return source_filename, version


def _get_pyarrow_release_tarball_url(version):
    return f'https://github.com/apache/arrow/archive/refs/tags/apache-arrow-{version}.tar.gz'


def expected_source_archive_name(req, dist_version):
    return f'apache-arrow-{dist_version}.tar.gz'


def expected_source_directory_name(req, dist_version):
    return f'apache-arrow-{dist_version}/arrow-apache-arrow-{dist_version}'


def get_build_system_dependencies(ctx, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.
    return dependencies.default_get_build_system_dependencies(
        ctx, req,
        sdist_root_dir / 'python',
    )


def get_build_backend_dependencies(ctx, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.
    return dependencies.default_get_build_backend_dependencies(
        ctx, req,
        sdist_root_dir / 'python',
    )


def get_install_dependencies(ctx, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.
    return dependencies.default_get_install_dependencies(
        ctx, req,
        sdist_root_dir / 'python',
    )


def build_wheel(ctx, build_env, extra_environ, req, sdist_root_dir):
    unpack_dir = sdist_root_dir.parent
    dist_dir = unpack_dir / 'dist'
    if not dist_dir.exists():
        dist_dir.mkdir(parents=True)

    ld_library_path = os.environ.get('LD_LIBRARY_PATH', '')
    cmake_prefix_path = os.environ.get('CMAKE_PREFIX_PATH', '')

    if platform.uname().machine == 'aarch64':
        # The VM on aarch64 dies if we do to much at once.
        wheel_build_parallel_level = 4
    else:
        # Try to encourage the build to use all of the CPUs available to
        # this process. If we can't get that set of CPUs, default to at
        # least 4 parallel threads.
        try:
            cpu_count = len(os.sched_getaffinity(0))
        except Exception as err:
            logger.debug('defaulting to 1 cpu (%s)', err)
            cpu_count = 1
            wheel_build_parallel_level = max([cpu_count, 4])

    # FIXME: Review settings at https://src.fedoraproject.org/rpms/libarrow/blob/rawhide/f/libarrow.spec#_759
    environ_vars = {
        # Used by cmake and make steps
        'PARQUET_TEST_DATA': f'{sdist_root_dir}/cpp/submodules/parquet-testing/data',
        'ARROW_TEST_DATA': '{sdist_root_dir}/testing/data',
        'ARROW_HOME': dist_dir,
        'LD_LIBRARY_PATH': f'{dist_dir}/lib:{ld_library_path}',
        'CMAKE_PREFIX_PATH': f'{dist_dir}:{cmake_prefix_path}',

        # Used when invoking pip to build the wheel
        'PYARROW_WITH_PARQUET': '1',
        'PYARROW_WITH_DATASET': '1',
        'PYARROW_PARALLEL': str(wheel_build_parallel_level),
        'PYARROW_BUNDLE_ARROW_CPP': '1',  # include C++ libs in the wheel
        'PYARROW_BUNDLE_ARROW_CPP_HEADERS': '1',  # include C++ headers in the wheel
    }
    environ_vars.update(extra_environ)

    # These options all need -D{name}=ON in the command line, so we do
    # that below when building cmake_cmd to keep this list easier to
    # read and manipulate.
    cmake_options = [
        'ARROW_BUILD_TESTS',
        'ARROW_COMPUTE',
        'ARROW_CSV',
        'ARROW_DATASET',
        'ARROW_FILESYSTEM',
        'ARROW_HDFS',
        'ARROW_JSON',
        'ARROW_PARQUET',
        'ARROW_WITH_BZ2',
        'ARROW_WITH_LZ4',
        'ARROW_WITH_SNAPPY',
        'ARROW_WITH_ZLIB',
        'ARROW_WITH_ZSTD',
        'PARQUET_REQUIRE_ENCRYPTION',
        # Not compatible with Fedora version of libbrotli. Enable for RHEL only?
        # 'ARROW_WITH_BROTLI',
    ]

    # We need to pass a command line option so that the cmake step
    # enables the CUDA build, *and* set an environment variable for
    # the wheel build step.
    if ctx.variant == 'cuda':
        cmake_options.append('ARROW_CUDA')
        environ_vars['PYARROW_WITH_CUDA'] = '1'

    # FIXME: Review settings at https://src.fedoraproject.org/rpms/libarrow/blob/rawhide/f/libarrow.spec#_695
    cmake_cmd = [
        'cmake',
        '-DCMAKE_BUILD_TYPE=Release',
        f'-DCMAKE_INSTALL_PREFIX={dist_dir}',
        '-DCMAKE_INSTALL_LIBDIR=lib',
    ] + [
        # Format the boolean options properly
        f'-D{opt}=ON'
        for opt in cmake_options
    ] + [
        '..',
    ]

    build_dir = sdist_root_dir / 'cpp/build'
    if not build_dir.exists():
        build_dir.mkdir(parents=True)

    # FIXME: The log locations are not going to be collected by the
    # artifacts step at the end of the pipeline because they're not in
    # a directory where logs are expected. Need to reconcile that by
    # moving them or adding those directories to where we find logs.

    cmake_log = unpack_dir / 'cmake.log'
    logger.info('running cmake [1/4] (logs in %s)', cmake_log)
    external_commands.run(
        cmake_cmd,
        cwd=build_dir,
        extra_environ=environ_vars,
        log_filename=cmake_log,
    )

    make_log = unpack_dir / 'make.log'
    logger.info('running make [2/4] (logs in %s)', make_log)
    external_commands.run(
        ['make', f'-j{wheel_build_parallel_level}'],
        cwd=build_dir,
        extra_environ=environ_vars,
        log_filename=make_log,
    )

    make_install_log = unpack_dir / 'make-install.log'
    logger.info('running make install [3/4] (logs in %s)', make_install_log)
    external_commands.run(
        ['make', 'install'],
        cwd=build_dir,
        extra_environ=environ_vars,
        log_filename=make_install_log,
    )

    build_wheel_log = unpack_dir / 'build-wheel.log'
    logger.info('building wheel [4/4] (logs in %s)', build_wheel_log)
    # Taken from wheels._default_build_wheel but we need to pass a
    # log_filename argument to run().
    with tempfile.TemporaryDirectory() as dir_name:
        build_wheel_cmd = [
            build_env.python, '-m', 'pip', '-vvv',
            '--disable-pip-version-check',
            'wheel',
            '--no-cache-dir',
            '--no-build-isolation',
            '--only-binary', ':all:',
            '--wheel-dir', ctx.wheels_build,
            '--no-deps',
            '--index-url', ctx.wheel_server_url,  # probably redundant, but just in case
            sdist_root_dir / 'python',
        ]
        external_commands.run(
            build_wheel_cmd,
            cwd=dir_name,
            extra_environ=environ_vars,
            log_filename=build_wheel_log,
        )
