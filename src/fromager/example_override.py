def expected_source_archive_name(req, dist_version):
    return f"fromager-test-{dist_version}.tar.gz"


def expected_source_directory_name(req, dist_version):
    return f"fromager-test-{dist_version}/different-prefix-fromager-test-{dist_version}"
