from . import bootstrap, build_order, canonicalize, step

commands = [
    bootstrap.bootstrap,
    build_order.build_order,
    step.step,
    canonicalize.canonicalize,
]
