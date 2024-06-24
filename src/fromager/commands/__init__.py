from . import bootstrap, build, build_order, canonicalize, download_sequence, step

commands = [
    bootstrap.bootstrap,
    build.build,
    build.build_sequence,
    build_order.build_order,
    step.step,
    canonicalize.canonicalize,
    download_sequence.download_sequence,
]
