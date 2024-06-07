from . import bootstrap, build, build_order, canonicalize, step

commands = [
    bootstrap.bootstrap,
    build.build,
    build_order.build_order,
    step.step,
    canonicalize.canonicalize,
]
