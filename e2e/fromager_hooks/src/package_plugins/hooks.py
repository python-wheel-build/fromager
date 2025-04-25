import logging
import pathlib

from packaging.requirements import Requirement

from fromager import context

logger = logging.getLogger(__name__)


def after_build_wheel(
    ctx: context.WorkContext,
    req: Requirement,
    dist_name: str,
    dist_version: str,
    sdist_filename: pathlib.Path,
    wheel_filename: pathlib.Path,
):
    logger.info(
        f"running post build hook in {__name__} for {sdist_filename} and {wheel_filename}"
    )
    test_file = sdist_filename.parent / "test-output-file.txt"
    logger.info(f"post-build hook writing to {test_file}")
    test_file.write_text(f"{dist_name}=={dist_version}")


def after_bootstrap(
    ctx: context.WorkContext,
    req: Requirement,
    dist_name: str,
    dist_version: str,
    sdist_filename: pathlib.Path | None,
    wheel_filename: pathlib.Path | None,
):
    logger.info(
        f"running post bootstrap hook in {__name__} for {sdist_filename} and {wheel_filename}"
    )
    test_file = ctx.work_dir / "test-output-file.txt"
    logger.info(f"post-bootstrap hook writing to {test_file}")
    test_file.write_text(f"{dist_name}=={dist_version}")


def after_prebuilt_wheel(
    ctx: context.WorkContext,
    req: Requirement,
    dist_name: str,
    dist_version: str,
    wheel_filename: pathlib.Path,
):
    logger.info(
        f"running post build hook in {__name__} for {wheel_filename}"
    )
    test_file = ctx.work_dir / "test-prebuilt.txt"
    logger.info(f"prebuilt-wheel hook writing to {test_file}")
    test_file.write_text(f"{dist_name}=={dist_version}")
