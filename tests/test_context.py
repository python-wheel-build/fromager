import json

from packaging.requirements import Requirement

from fromager import context, settings


def test_seen(tmp_context):
    req = Requirement("testdist")
    version = "1.2"
    assert not tmp_context.has_been_seen(req, version)
    tmp_context.mark_as_seen(req, version)
    assert tmp_context.has_been_seen(req, version)


def test_seen_extras(tmp_context):
    req1 = Requirement("testdist")
    req2 = Requirement("testdist[extra]")
    version = "1.2"
    assert not tmp_context.has_been_seen(req1, version)
    tmp_context.mark_as_seen(req1, version)
    assert tmp_context.has_been_seen(req1, version)
    assert not tmp_context.has_been_seen(req2, version)
    tmp_context.mark_as_seen(req2, version)
    assert tmp_context.has_been_seen(req1, version)
    assert tmp_context.has_been_seen(req2, version)


def test_seen_name_canonicalization(tmp_context):
    req = Requirement("flit_core")
    version = "1.2"
    assert not tmp_context.has_been_seen(req, version)
    tmp_context.mark_as_seen(req, version)
    assert tmp_context.has_been_seen(req, version)


def test_build_order(tmp_context):
    tmp_context.add_to_build_order(
        "build_backend",
        Requirement("buildme>1.0"),
        "6.0",
        [("toplevel", Requirement("buildme>1.0"), "6.0")],
        "url",
        "sdist",
    )
    tmp_context.add_to_build_order(
        "dependency",
        Requirement("testdist>1.0"),
        "1.2",
        [
            ("toplevel", Requirement("buildme>1.0"), "6.0"),
            ("install", Requirement("testdist>1.0"), "1.0"),
        ],
        "url",
        "sdist",
    )
    contents_str = tmp_context._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            "type": "build_backend",
            "req": "buildme>1.0",
            "dist": "buildme",
            "version": "6.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["toplevel", "buildme>1.0", "6.0"],
            ],
        },
        {
            "type": "dependency",
            "req": "testdist>1.0",
            "dist": "testdist",
            "version": "1.2",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["toplevel", "buildme>1.0", "6.0"],
                ["install", "testdist>1.0", "1.0"],
            ],
        },
    ]
    assert expected == contents


def test_build_order_repeats(tmp_context):
    tmp_context.add_to_build_order(
        "build_backend",
        Requirement("buildme>1.0"),
        "6.0",
        [("toplevel", Requirement("buildme>1.0"), "6.0")],
        "url",
        "sdist",
    )
    tmp_context.add_to_build_order(
        "build_backend",
        Requirement("buildme>1.0"),
        "6.0",
        [("toplevel", Requirement("buildme>1.0"), "6.0")],
        "url",
        "sdist",
    )
    tmp_context.add_to_build_order(
        "build_backend",
        Requirement("buildme[extra]>1.0"),
        "6.0",
        [("toplevel", Requirement("buildme[extra]>1.0"), "6.0")],
        "url",
        "sdist",
    )
    contents_str = tmp_context._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            "type": "build_backend",
            "req": "buildme>1.0",
            "dist": "buildme",
            "version": "6.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["toplevel", "buildme>1.0", "6.0"],
            ],
        },
    ]
    assert expected == contents


def test_build_order_name_canonicalization(tmp_context):
    tmp_context.add_to_build_order(
        "build_backend",
        Requirement("flit-core>1.0"),
        "3.9.0",
        [("build_backend", Requirement("flit-core>1.0"), "3.9.0")],
        "url",
        "sdist",
    )
    tmp_context.add_to_build_order(
        "build_backend",
        Requirement("flit_core>1.0"),
        "3.9.0",
        [("build_backend", Requirement("flit-core>1.0"), "3.9.0")],
        "url",
        "sdist",
    )
    contents_str = tmp_context._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            "type": "build_backend",
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.9.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
            "why": [
                ["build_backend", "flit-core>1.0", "3.9.0"],
            ],
        },
    ]
    assert expected == contents


def test_parallel_jobs(tmp_context: context.WorkContext):
    req = Requirement("testdist")
    tmp_context.jobs_cpu_scaling = 1
    tmp_context.jobs_memory_scaling = 2
    assert tmp_context.cpu_count() == 8
    assert tmp_context.available_memory_gib() == 15.1

    assert tmp_context.parallel_jobs(req) == 7

    tmp_context.cpu_count.return_value = 4
    assert tmp_context.parallel_jobs(req) == 4

    tmp_context.available_memory_gib.return_value = 4.1
    assert tmp_context.parallel_jobs(req) == 2

    tmp_context.available_memory_gib.return_value = 1.5
    assert tmp_context.parallel_jobs(req) == 1

    tmp_context.available_memory_gib.return_value = 23
    tmp_context.jobs_memory_scaling = 10
    assert tmp_context.parallel_jobs(req) == 2

    tmp_context.cpu_count.return_value = 16
    tmp_context.available_memory_gib.return_value = 20
    tmp_context.settings = settings.Settings(
        {"build_option": {req.name: {"cpu_scaling": 4, "memory_scaling": 4}}}
    )
    assert tmp_context.parallel_jobs(req) == 4

    tmp_context.cpu_count.return_value = 32
    tmp_context.available_memory_gib.return_value = 25
    assert tmp_context.parallel_jobs(req) == 6

    tmp_context.max_jobs = 4
    assert tmp_context.parallel_jobs(req) == 4
