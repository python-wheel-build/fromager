from . import (
    bootstrap,
    build,
    build_order,
    canonicalize,
    download_sequence,
    graph,
    lint,
    lint_requirements,
    list_overrides,
    migrate_config,
    minimize,
    server,
    stats,
    step,
)

commands = [
    bootstrap.bootstrap,
    build.build,
    build.build_sequence,
    build.build_parallel,
    build_order.build_order,
    graph.graph,
    lint.lint,
    list_overrides.list_overrides,
    migrate_config.migrate_config,
    minimize.minimize,
    stats.stats,
    step.step,
    canonicalize.canonicalize,
    download_sequence.download_sequence,
    server.wheel_server,
    migrate_config.migrate_config,
    lint_requirements.lint_requirements,
]
