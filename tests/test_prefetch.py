"""Tests for prefetch bundle export and validation."""

from __future__ import annotations

import json
import pathlib
import tarfile
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import build_environment, context, prefetch
from fromager.commands import build
from fromager.requirements_file import RequirementType


def _write_bootstrap_outputs(ctx: context.WorkContext) -> None:
    ctx.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("demo==1.0"),
        req_version=Version("1.0"),
    )
    ctx.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("binary-demo==2.0"),
        req_version=Version("2.0"),
        pre_built=True,
    )
    ctx.dependency_graph.add_dependency(
        parent_name=canonicalize_name("demo"),
        parent_version=Version("1.0"),
        req_type=RequirementType.BUILD_SYSTEM,
        req=Requirement("setuptools>=70"),
        req_version=Version("80.0"),
    )
    ctx.dependency_graph.add_dependency(
        parent_name=canonicalize_name("setuptools"),
        parent_version=Version("80.0"),
        req_type=RequirementType.INSTALL,
        req=Requirement("packaging>=23"),
        req_version=Version("24.0"),
    )
    with ctx.graph_file.open("w", encoding="utf-8") as f:
        ctx.dependency_graph.serialize(f)
    build_order = [
        {
            "req": "packaging>=23",
            "constraint": "",
            "dist": "packaging",
            "version": "24.0",
            "prebuilt": False,
            "source_url": "https://pkg.test/packaging-24.0.tar.gz",
            "source_url_type": "sdist",
            "build_requirements": [],
            "prepared_source_root": "packaging-24.0/packaging-24.0",
            "prepared_source_workspace": "packaging-24.0",
        },
        {
            "req": "setuptools>=70",
            "constraint": "",
            "dist": "setuptools",
            "version": "80.0",
            "prebuilt": False,
            "source_url": "https://pkg.test/setuptools-80.0.tar.gz",
            "source_url_type": "sdist",
            "build_requirements": [],
            "prepared_source_root": "setuptools-80.0/setuptools-80.0",
            "prepared_source_workspace": "setuptools-80.0",
        },
        {
            "req": "demo==1.0",
            "constraint": "",
            "dist": "demo",
            "version": "1.0",
            "prebuilt": False,
            "source_url": "https://pkg.test/demo-1.0.tar.gz",
            "source_url_type": "sdist",
            "build_requirements": ["packaging==24.0", "setuptools==80.0"],
            "prepared_source_root": "demo-1.0/demo-1.0",
            "prepared_source_workspace": "demo-1.0",
        },
        {
            "req": "binary-demo==2.0",
            "constraint": "",
            "dist": "binary-demo",
            "version": "2.0",
            "prebuilt": True,
            "source_url": "https://pkg.test/binary_demo-2.0-py3-none-any.whl",
            "source_url_type": "prebuilt",
            "build_requirements": [],
        },
    ]
    ctx.work_dir.joinpath("build-order.json").write_text(
        json.dumps(build_order), encoding="utf-8"
    )
    ctx.work_dir.joinpath("constraints.txt").write_text("demo==1.0\n", encoding="utf-8")
    ctx.sdists_builds.joinpath("demo-1.0.tar.gz").write_bytes(b"patched source")
    ctx.sdists_builds.joinpath("setuptools-80.0.tar.gz").write_bytes(
        b"patched setuptools"
    )
    ctx.sdists_builds.joinpath("packaging-24.0.tar.gz").write_bytes(
        b"patched packaging"
    )
    for dist, version in (
        ("demo", "1.0"),
        ("packaging", "24.0"),
        ("setuptools", "80.0"),
    ):
        source_root = ctx.work_dir / f"{dist}-{version}" / f"{dist}-{version}"
        source_root.mkdir(parents=True)
        source_root.joinpath("prepared.txt").write_text(dist)
    ctx.wheels_prebuilt.joinpath("binary_demo-2.0-py3-none-any.whl").write_bytes(
        b"prebuilt wheel"
    )
    ctx.wheels_downloads.joinpath("setuptools-80.0-py3-none-any.whl").write_bytes(
        b"bootstrap wheel"
    )
    ctx.wheels_downloads.joinpath("packaging-24.0-py3-none-any.whl").write_bytes(
        b"transitive bootstrap wheel"
    )
    ctx.wheels_downloads.joinpath("unrelated-9.0-py3-none-any.whl").write_bytes(
        b"stale wheel"
    )


def test_export_prefetch_bundle(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)

    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")

    assert bundle.manifest.format_version == 1
    assert bundle.manifest.variant == "cpu"
    assert bundle.build_order_file.name == "build-order.json"
    with tarfile.open(
        bundle.package_artifact("demo", "1.0", prebuilt=False)
    ) as archive:
        prepared_file = archive.extractfile("demo-1.0/prepared.txt")
        assert prepared_file is not None
        assert prepared_file.read() == b"demo"
    assert (
        bundle.package_artifact("binary-demo", "2.0", prebuilt=True).read_bytes()
        == b"prebuilt wheel"
    )
    assert {path.name for path in bundle.wheelhouse_dirs} == {"wheels"}
    demo = next(
        package for package in bundle.manifest.packages if package.dist == "demo"
    )
    assert set(demo.build_requirements) == {
        "packaging==24.0",
        "setuptools==80.0",
    }
    assert {
        pathlib.Path(wheel.artifact.path).name for wheel in bundle.manifest.wheels
    } == {
        "packaging-24.0-py3-none-any.whl",
        "setuptools-80.0-py3-none-any.whl",
    }


def test_export_prefetch_bundle_includes_prepared_siblings(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    package_dir = tmp_context.work_dir / "demo-1.0"
    source_dir = package_dir / "demo-1.0"
    source_dir.joinpath("prepared.txt").unlink()
    (source_dir / "setup.py").write_text("# setup")
    (package_dir / "prepared-dependency").mkdir()
    (package_dir / "prepared-dependency" / "README").write_text("prepared")
    (package_dir / "build-3.12.14").mkdir()

    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")

    with tarfile.open(
        bundle.package_artifact("demo", "1.0", prebuilt=False)
    ) as archive:
        names = set(archive.getnames())
    assert "demo-1.0/setup.py" in names
    assert "prepared-dependency/README" in names
    assert not any("build-3.12.14" in name for name in names)


def test_export_prefetch_bundle_preserves_build_named_source_root(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    workspace = tmp_context.work_dir / "demo-1.0"
    source_root = workspace / "demo-1.0"
    source_root.rename(workspace / "build-1.0")
    workspace.rename(tmp_context.work_dir / "build-1.0")
    build_order_path = tmp_context.work_dir / "build-order.json"
    build_order = json.loads(build_order_path.read_text(encoding="utf-8"))
    demo = next(entry for entry in build_order if entry["dist"] == "demo")
    demo["prepared_source_root"] = "build-1.0/build-1.0"
    demo["prepared_source_workspace"] = "build-1.0"
    build_order_path.write_text(json.dumps(build_order), encoding="utf-8")

    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")

    with tarfile.open(
        bundle.package_artifact("demo", "1.0", prebuilt=False)
    ) as archive:
        assert "build-1.0/prepared.txt" in archive.getnames()


def test_export_prefetch_bundle_excludes_nested_build_outputs(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    source_root = tmp_context.work_dir / "demo-1.0" / "demo-1.0"
    (source_root / "subproject" / "build" / "lib").mkdir(parents=True)
    (source_root / "subproject" / "build" / "lib" / "generated.c").write_text(
        "generated"
    )
    (source_root / "vendor" / "rust" / "target" / "debug").mkdir(parents=True)
    (source_root / "vendor" / "rust" / "target" / "debug" / "artifact.o").write_text(
        "generated"
    )
    (source_root / "demo.egg-info").mkdir()
    (source_root / "demo.egg-info" / "PKG-INFO").write_text("generated")
    (source_root / "__pycache__").mkdir()
    (source_root / "__pycache__" / "module.pyc").write_bytes(b"generated")
    (source_root / "src").mkdir()
    (source_root / "src" / "module.py").write_text("source")

    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")

    with tarfile.open(
        bundle.package_artifact("demo", "1.0", prebuilt=False)
    ) as archive:
        names = set(archive.getnames())
    assert "demo-1.0/src/module.py" in names
    assert not any(
        "/build/" in name
        or "/target/" in name
        or ".egg-info" in name
        or "__pycache__" in name
        or name.endswith(".pyc")
        for name in names
    )


def test_export_prefetch_bundle_requires_prepared_workspace(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    source_root = tmp_context.work_dir / "demo-1.0" / "demo-1.0"
    source_root.rename(tmp_context.work_dir / "missing-demo-source")

    with pytest.raises(FileNotFoundError, match="prepared source workspace is missing"):
        prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")


def test_export_prefetch_bundle_normalizes_zip_source_name(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    (tmp_context.sdists_builds / "demo-1.0.tar.gz").rename(
        tmp_context.sdists_builds / "demo-1.0.zip"
    )

    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")
    artifact = bundle.package_artifact("demo", "1.0", prebuilt=False)

    assert artifact.name == "demo-1.0.tar.gz"
    with tarfile.open(artifact):
        pass


def test_load_prefetch_bundle_rejects_tampered_artifact(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")
    sdist = bundle.package_artifact("demo", "1.0", prebuilt=False)
    sdist.write_bytes(b"corrupt source")

    with pytest.raises(ValueError, match="wrong size"):
        prefetch.load_prefetch_bundle(bundle.root)


def test_load_prefetch_bundle_rejects_tampered_wheel(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")
    wheel = bundle.root / bundle.manifest.wheels[0].artifact.path
    wheel.write_bytes(b"corrupt wheel")

    with pytest.raises(ValueError, match="wrong size"):
        prefetch.load_prefetch_bundle(bundle.root)


def test_copy_artifact_rejects_symlink_destination(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    source = tmp_path / "source.whl"
    source.write_bytes(b"source")
    outside = tmp_path / "outside.whl"
    outside.write_bytes(b"outside")
    destination = root / "wheels" / "source.whl"
    destination.parent.mkdir()
    destination.symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        prefetch._copy_artifact(root, source, pathlib.Path("wheels/source.whl"))

    assert outside.read_bytes() == b"outside"


def test_load_prefetch_bundle_rejects_variant_mismatch(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")

    with pytest.raises(ValueError, match="does not match"):
        prefetch.load_prefetch_bundle(bundle.root, expected_variant="cuda")


def test_load_prefetch_bundle_rejects_settings_mismatch(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")
    tmp_context.settings.max_jobs = 2

    with pytest.raises(ValueError, match="settings and patches"):
        bundle.validate_configuration(tmp_context)


def test_configuration_fingerprint_changes_with_settings(
    tmp_context: context.WorkContext,
) -> None:
    packages = [("demo", "1.0")]
    original = prefetch.configuration_fingerprint(tmp_context, packages)

    tmp_context.settings.max_jobs = 1

    assert prefetch.configuration_fingerprint(tmp_context, packages) != original


def test_load_prefetch_bundle_rejects_fromager_version_mismatch(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")
    manifest_path = bundle.root / prefetch.MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fromager_version"] = "999.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="fromager_version"):
        prefetch.load_prefetch_bundle(bundle.root)


def test_offline_context_uses_local_wheelhouses(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    wheelhouse = tmp_path / "wheelhouse"

    tmp_context.enable_offline_build([wheelhouse])

    assert tmp_context.offline
    assert tmp_context.pip_wheel_server_args == [
        "--no-index",
        "--offline",
        "--find-links",
        str(tmp_context.wheels_downloads),
        "--find-links",
        str(wheelhouse),
    ]


def test_offline_context_uses_prefetched_constraints(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    constraints = tmp_path / "merged-constraints.txt"
    constraints.write_text("setuptools==80.0\n", encoding="utf-8")

    tmp_context.enable_offline_build([], constraints_file=constraints)

    assert tmp_context.pip_constraint_args == ["--constraint", str(constraints)]


def test_offline_build_environment_install_uses_network_isolation(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    tmp_context.network_isolation = True
    tmp_context.enable_offline_build([tmp_path / "wheelhouse"])
    build_env = Mock(spec=build_environment.BuildEnvironment)
    build_env._ctx = tmp_context
    build_env.path = tmp_path / "build-env"

    build_environment.BuildEnvironment.install(
        build_env, [Requirement("setuptools==80.0")]
    )

    build_env.run.assert_called_once()
    assert build_env.run.call_args.kwargs["network_isolation"] is True


def test_offline_build_environment_blocks_nested_package_indexes(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    constraints = tmp_path / "constraints.txt"
    tmp_context.enable_offline_build([wheelhouse], constraints_file=constraints)
    build_env = object.__new__(build_environment.BuildEnvironment)
    build_env._ctx = tmp_context
    build_env.path = tmp_path / "build-env"

    environ = build_env.get_venv_environ({"PATH": "/usr/bin"})

    assert environ["UV_OFFLINE"] == "true"
    assert environ["UV_NO_CACHE"] == "true"
    assert environ["PIP_NO_INDEX"] == "1"
    assert environ["PIP_FIND_LINKS"] == (f"{tmp_context.wheels_downloads} {wheelhouse}")
    assert environ["PIP_CONSTRAINT"] == str(constraints)


def test_build_uses_prefetched_sdist_without_preparing_source(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")
    req = Requirement("demo==1.0")
    tmp_context.wheel_server_url = "http://127.0.0.1:1234/simple/"
    source_root = tmp_context.work_dir / "demo-1.0" / "demo-1.0"
    source_root.mkdir(parents=True, exist_ok=True)
    built_wheel = tmp_context.wheels_build / "demo-1.0-py3-none-any.whl"
    built_wheel.write_bytes(b"wheel")
    built_sdist = tmp_context.sdists_builds / "demo-1.0.tar.gz"
    stale_wheel = tmp_context.wheels_downloads / built_wheel.name
    stale_wheel.write_bytes(b"stale wheel")
    build_env = Mock(spec=build_environment.BuildEnvironment)
    build_env.path = tmp_path / "build-env"

    with (
        patch.object(
            build, "_is_wheel_built", return_value=None
        ) as remote_wheel_lookup,
        patch.object(build.sources, "download_source") as download_source,
        patch.object(build.sources, "prepare_source") as prepare_source,
        patch.object(
            build.sources, "unpack_source", return_value=(source_root, True)
        ) as unpack_source,
        patch.object(
            build.sources, "build_sdist", return_value=built_sdist
        ) as build_sdist,
        patch.object(
            build.build_environment,
            "prepare_build_environment",
        ) as discover_build_environment,
        patch.object(
            build.build_environment,
            "prepare_build_environment_from_prefetch",
            return_value=build_env,
        ) as prepare_build_environment,
        patch.object(
            build.wheels, "build_wheel", return_value=built_wheel
        ) as build_wheel,
        patch.object(build.hooks, "run_post_build_hooks") as post_build_hooks,
        patch.object(build.server, "update_wheel_mirror"),
    ):
        build._build(
            wkctx=tmp_context,
            resolved_version=Version("1.0"),
            req=req,
            source_download_url="https://pkg.test/demo-1.0.tar.gz",
            force=False,
            cache_wheel_server_url=None,
            prefetch_bundle=bundle,
        )

    unpack_source.assert_called_once_with(
        ctx=tmp_context,
        req=req,
        version=Version("1.0"),
        source_filename=bundle.package_artifact("demo", "1.0", prebuilt=False),
        reuse_existing=False,
    )
    download_source.assert_not_called()
    prepare_source.assert_not_called()
    build_sdist.assert_called_once_with(
        ctx=tmp_context,
        req=req,
        version=Version("1.0"),
        sdist_root_dir=source_root,
        build_env=build_env,
    )
    assert post_build_hooks.call_args.kwargs["sdist_filename"] == built_sdist
    discover_build_environment.assert_not_called()
    assert prepare_build_environment.call_args.kwargs["build_requirements"] == {
        Requirement("packaging==24.0"),
        Requirement("setuptools==80.0"),
    }
    remote_wheel_lookup.assert_not_called()
    build_wheel.assert_called_once()


def test_clean_prefetched_source_removes_workspace(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    workspace = tmp_path / "workspace"
    source_root = workspace / "demo-1.0"
    sibling = workspace / "prepared-dependency"
    source_root.mkdir(parents=True)
    sibling.mkdir()
    build_env = Mock(spec=build_environment.BuildEnvironment)
    build_env.path = workspace / "build-3.12.0"
    build_env.path.mkdir()
    prepared = build._PreparedBuildSource(
        sdist_filename=tmp_path / "demo-1.0.tar.gz",
        source_root_dir=source_root,
        build_env=build_env,
        workspace_dir=workspace,
    )

    build._clean_prepared_source(tmp_context, prepared)

    assert not workspace.exists()


def test_prefetched_prebuilt_ignores_stale_output_wheel(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")
    wheel_name = "binary_demo-2.0-py3-none-any.whl"
    stale_wheel = tmp_context.wheels_downloads / wheel_name
    stale_wheel.write_bytes(b"stale wheel")

    with (
        patch.object(
            tmp_context,
            "package_build_info",
            return_value=Mock(pre_built=True),
        ),
        patch.object(build.hooks, "run_prebuilt_wheel_hooks") as prebuilt_hooks,
        patch.object(build.server, "update_wheel_mirror"),
    ):
        result = build._build(
            wkctx=tmp_context,
            resolved_version=Version("2.0"),
            req=Requirement("binary-demo==2.0"),
            source_download_url=f"https://pkg.test/{wheel_name}",
            force=False,
            cache_wheel_server_url=None,
            prefetch_bundle=bundle,
        )

    staged_wheel = tmp_context.wheels_build / wheel_name
    assert staged_wheel.read_bytes() == b"prebuilt wheel"
    assert result.skipped is False
    assert prebuilt_hooks.call_args.kwargs["wheel_filename"] == staged_wheel


def test_build_sequence_accepts_prefetch_directory(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    _write_bootstrap_outputs(tmp_context)
    bundle = prefetch.export_prefetch_bundle(tmp_context, tmp_path / "prefetch")
    built = Mock(
        prebuilt=False,
        skipped=False,
        wheel_filename=pathlib.Path("demo-1.0-py3-none-any.whl"),
    )

    with (
        patch.object(build, "_build", return_value=built) as build_one,
        patch.object(build.server, "start_wheel_server") as start_wheel_server,
        patch.object(build.metrics, "summarize"),
        patch.object(build, "_summary"),
    ):
        result = CliRunner().invoke(
            build.build_sequence,
            ["--prefetch-dir", str(bundle.root)],
            obj=tmp_context,
        )

    assert result.exit_code == 0
    assert tmp_context.offline
    assert tmp_context.network_isolation is True
    assert build_one.call_count == 4
    assert build_one.call_args.kwargs["prefetch_bundle"].root == bundle.root
    start_wheel_server.assert_not_called()
