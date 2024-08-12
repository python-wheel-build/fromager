import collections
import csv
import json
import pathlib
import sys

import click

from .. import clickext, overrides


@click.group()
def build_order() -> None:
    "Commands for working with build-order files"
    pass


@build_order.command()
@click.option(
    "-o",
    "--output",
    type=clickext.ClickPath(),
    help="output file to create",
)
@click.argument("build_order_file")
def as_csv(build_order_file: str, output: pathlib.Path | None) -> None:
    """Create a comma-separated-value file from the build order file

    BUILD_ORDER_FILE is one or more build-order.json files to convert

    Creates a file suitable for import into a spreadsheet including the
    distribution name, version, original requirement, dependency type,
    whether the package is pre-built, the build order step number, and
    a full dependency chain leading to the requirment.

    """
    fields = [
        ("dist", "Distribution Name"),
        ("version", "Version"),
        ("req", "Original Requirement"),
        ("type", "Dependency Type"),
        ("prebuilt", "Pre-built Package"),
        ("order", "Build Order"),
    ]
    headers = {n: v for n, v in fields}
    fieldkeys = [f[0] for f in fields]
    fieldnames = [f[1] for f in fields]

    build_order = []
    with open(build_order_file, "r") as f:
        for i, entry in enumerate(json.load(f), 1):
            # Add an order column, not in the original source file, in
            # case someone wants to sort the output on another field.
            entry["order"] = i
            # Replace the short keys with the longer human-readable
            # headers we want in the CSV output.
            new_entry = {headers[f]: entry[f] for f in fieldkeys}
            build_order.append(new_entry)

    outfile = open(output, "w") if output else sys.stdout

    try:
        writer = csv.DictWriter(
            outfile, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC
        )
        writer.writeheader()
        writer.writerows(build_order)
    finally:
        if output:
            outfile.close()


@build_order.command()
@click.option(
    "-o",
    "--output",
    type=clickext.ClickPath(),
    help="output file to create",
)
@click.argument("build_order_file", nargs=-1)
def summary(build_order_file: list[str], output: pathlib.Path | None) -> None:
    """Summarize the build order files

    BUILD_ORDER_FILE is one or more build-order.json files to convert

    Creates a comma-separated-value file including the distribution
    name, the build order file that included it, which versions are
    used in each, and where they match.

    """
    dist_to_input_file: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for filename in build_order_file:
        with open(filename, "r") as f:
            build_order = json.load(f)
        for step in build_order:
            key = overrides.pkgname_to_override_module(step["dist"])
            dist_to_input_file[key][filename] = step["version"]

    outfile = open(output, "w") if output else sys.stdout

    # The build order files are organized in directories named for the
    # image. Pull those names out of the files given.
    image_column_names = tuple(
        pathlib.Path(filename).parent.name for filename in build_order_file
    )

    writer = csv.writer(outfile, quoting=csv.QUOTE_NONNUMERIC)
    writer.writerow(("Distribution Name",) + image_column_names + ("Same Version",))
    for dist, present_in_files in sorted(dist_to_input_file.items()):
        all_versions = set()
        row = [dist]
        for filename in build_order_file:
            v = present_in_files.get(filename, "")
            row.append(v)
            if v:
                all_versions.add(v)
        row.append(str(len(all_versions) == 1))
        writer.writerow(row)

    if output:
        outfile.close()
