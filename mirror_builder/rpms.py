import collections
import csv
import json
import logging
import subprocess
import sys

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)


def _get_rpms():
    cmd = ['sudo', 'dnf', '--quiet', 'repoquery', '--queryformat', '%{name} %{version}']
    logger.debug(' '.join(cmd))
    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    for line in completed.stdout.decode('utf-8').splitlines():
        yield line.split()


def do_find_rpms(args):
    with open(args.build_order_file, 'r') as f:
        build_order = json.load(f)

    # RPMs can have multiple versions.
    rpm_versions = collections.defaultdict(list)
    for n, v in _get_rpms():
        rpm_versions[n].append(v)

    if args.output:
        outfile = open(args.output, 'w')
    else:
        outfile = sys.stdout
    writer = csv.writer(outfile)
    writer.writerow(("Result", "Dist Name", "Dist Version", "RPM Name", "RPM Version"))

    def show(match, step, rpm_name='', rpm_version=''):
        writer.writerow((match, step['dist'], step['version'],
                         rpm_name, rpm_version))
        if args.output:
            outfile.flush()

    for step in build_order:

        candidate_versions = []
        candidates = [
            step['dist'],
            canonicalize_name(step['dist']),
            'python3-' + step['dist'],
            'python3-' + canonicalize_name(step['dist']),
        ]
        for candidate in candidates:
            if candidate in rpm_versions:
                rpm_name = candidate
                candidate_versions = rpm_versions[candidate]
                break
        else:
            show('NO RPM', step)
            continue

        # Look first for a match. If we don't find one, report all of
        # the other mismatched versions (there may be multiples).
        others = []
        dist_version = Version(step['version'])
        for rpm_version_str in candidate_versions:
            try:
                rpm_version = Version(rpm_version_str)
            except InvalidVersion:
                # Some RPM versions can't be parsed as Python package
                # versions (tzdata). We can't safely compare the
                # strings, except for exact equality, so fall back to
                # saying the versions are different.
                rpm_version = rpm_version_str
                if step['version'] == rpm_version_str:
                    result = 'OK'
                else:
                    result = 'DIFF'

            else:
                if dist_version == rpm_version:
                    result = 'OK'
                elif rpm_version < dist_version:
                    result = 'OLD'
                else:
                    result = 'DIFF'

            if result == 'OK':
                show('OK', step, rpm_name, rpm_version)
                break
            else:
                others.append((result, step, rpm_name, rpm_version))

        # If we didn't break out after finding an exact match, report
        # what we did find.
        else:
            for o in others:
                show(*o)

    if args.output:
        outfile.close()
