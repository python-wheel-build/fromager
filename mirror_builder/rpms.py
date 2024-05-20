import csv
import json
import subprocess
import sys

from packaging.version import Version


def _query(dist_name):
    for query_name in [f'python3-{dist_name}', dist_name]:
        completed = subprocess.run(
            ['sudo', 'dnf', 'repoquery', '--queryformat',
             '%{name} %{version}', query_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        for line in completed.stdout.decode('utf-8').splitlines():
            yield line.split()


def do_find_rpms(args):
    with open(args.build_order_file, 'r') as f:
        build_order = json.load(f)

    if args.output:
        outfile = open(args.output, 'w')
    else:
        outfile = sys.stdout
    writer = csv.writer(outfile)
    writer.writerow(("Result", "Dist Name", "Dist Version", "RPM Name", "RPM Version"))

    def show(match, step, rpm_name='', rpm_version=''):
        writer.writerow((match, step['dist'], step['version'],
                         rpm_name, rpm_version))

    for step in build_order:
        rpm_info = list(_query(step['dist']))

        if not rpm_info:
            show('NO RPM', step)
            continue

        # Look first for a match. If we don't find one, report all of
        # the other mismatched versions (there may be multiples).
        others = []
        for rpm_name, rpm_version_str in rpm_info:
            dist_version = Version(step['version'])
            rpm_version = Version(rpm_version_str)
            if dist_version == rpm_version:
                show('OK', step, rpm_name, rpm_version)
                break
            elif rpm_version < dist_version:
                others.append(('OLD', step, rpm_name, rpm_version))
            else:
                others.append(('DIFF', step, rpm_name, rpm_version))
        else:
            for o in others:
                show(*o)

    if args.output:
        outfile.close()
