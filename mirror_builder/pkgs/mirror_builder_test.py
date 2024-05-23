def expected_source_archive_name(req, dist_version):
    return f'mirror-builder-test-{dist_version}.tar.gz'


def expected_source_directory_name(req, dist_version):
    return f'mirror-builder-test-{dist_version}/different-prefix-mirror-builder-test-{dist_version}'
