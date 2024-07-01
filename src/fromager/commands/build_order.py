import collections
import csv
import itertools
import json
import pathlib
import sys

import click
from packaging.requirements import Requirement

from .. import clickext, overrides


@click.group()
def build_order():
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
def as_csv(build_order_file: str, output: pathlib.Path | None):
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
        ("why", "Dependency Chain"),
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
            # Reformat the why field
            new_entry["Dependency Chain"] = " ".join(
                f"-{dep_type}-> {Requirement(req).name}({version})"
                for dep_type, req, version in entry["why"]
            )
            build_order.append(new_entry)

    if output:
        outfile = open(output, "w")
    else:
        outfile = sys.stdout

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
def summary(build_order_file: list[str], output: pathlib.Path | None):
    """Summarize the build order files

    BUILD_ORDER_FILE is one or more build-order.json files to convert

    Creates a comma-separated-value file including the distribution
    name, the build order file that included it, which versions are
    used in each, and where they match.

    """
    dist_to_input_file = collections.defaultdict(dict)
    for filename in build_order_file:
        with open(filename, "r") as f:
            build_order = json.load(f)
        for step in build_order:
            key = overrides.pkgname_to_override_module(step["dist"])
            dist_to_input_file[key][filename] = step["version"]

    if output:
        outfile = open(output, "w")
    else:
        outfile = sys.stdout

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
        row.append(len(all_versions) == 1)
        writer.writerow(row)

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
def graph(build_order_file: list[str], output: pathlib.Path | None):
    """Write a graphviz-compatible dot file representing the build order dependencies

    BUILD_ORDER_FILE is one or more build-order.json files to convert

    """

    def fmt_req(req, version):
        req = Requirement(req)
        name = overrides.pkgname_to_override_module(req.name)
        return (
            f'{name}{"[" + ",".join(req.extras) + "]" if req.extras else ""}=={version}'
        )

    def new_node(req):
        if req not in nodes:
            nodes[req] = {
                "nid": "node" + str(next(node_ids)),
                "prebuilt": False,
            }
        return nodes[req]

    def update_node(req, prebuilt=False):
        node_details = new_node(req)
        if (not node_details["prebuilt"]) and prebuilt:
            node_details["prebuilt"] = True
        return req

    # Track unique ids for nodes since the labels may not be
    # syntactically correct.
    node_ids = itertools.count(1)
    # Map formatted requirement text to node details
    nodes = {}
    edges = []

    for filename in build_order_file:
        with open(filename, "r") as f:
            build_order = json.load(f)

        for step in build_order:
            update_node(
                fmt_req(step["dist"], step["version"]), prebuilt=step["prebuilt"]
            )
            try:
                why = step["why"]
                if len(why) == 0:
                    # should not happen
                    continue
                elif len(why) == 1:
                    # Lone node requiring nothing to build.
                    pass
                else:
                    parent_info = why[0]
                    for child_info in why[1:]:
                        parent = update_node(fmt_req(parent_info[1], parent_info[2]))
                        child = update_node(fmt_req(child_info[1], child_info[2]))
                        edge = (parent, child)
                        # print(edge, nodes[edge[0]], nodes[edge[1]])
                        if edge not in edges:
                            edges.append(edge)
                        parent_info = child_info
            except Exception as err:
                raise Exception(f"Error processing {filename} at {step}") from err

    if output:
        outfile = open(output, "w")
    else:
        outfile = sys.stdout
    try:
        outfile.write("digraph {\n")

        # Determine some nodes with special characteristics
        all_nodes = set(n["nid"] for n in nodes.values())
        # left = set(nodes[p]['nid'] for p, _ in edges)
        right = set(nodes[c]["nid"] for _, c in edges)
        # Toplevel nodes have no incoming connections
        toplevel_nodes = all_nodes - right
        # Leaves have no outgoing connections
        # leaves = all_nodes - left

        for req, node_details in nodes.items():
            nid = node_details["nid"]

            node_attrs = [("label", req)]
            if node_details["prebuilt"]:
                node_attrs.extend(
                    [
                        ("style", "filled"),
                        ("color", "darkred"),
                        ("fontcolor", "white"),
                        ("tooltip", "pre-built package"),
                    ]
                )
            elif nid in toplevel_nodes:
                node_attrs.extend(
                    [
                        ("style", "filled"),
                        ("color", "darkgreen"),
                        ("fontcolor", "white"),
                        ("tooltip", "toplevel package"),
                    ]
                )
            node_attr_text = ",".join(f'{a}="{b}"' for a, b in node_attrs)

            outfile.write(f"  {nid} [{node_attr_text}];\n")

        outfile.write("\n")
        if len(toplevel_nodes) > 1:
            outfile.write("  /* toplevel nodes should all be at the same level */\n")
            outfile.write(f"  {{rank=same; {' '.join(toplevel_nodes)};}}\n\n")
        # if len(leaves) > 1:
        #     outfile.write('  /* leaf nodes should all be at the same level */\n')
        #     outfile.write('  {rank=same; %s;}\n\n' % " ".join(leaves))

        for parent_req, child_req in edges:
            parent_node = nodes[parent_req]
            parent_nid = parent_node["nid"]
            child_node = nodes[child_req]
            child_nid = child_node["nid"]
            outfile.write(f"  {parent_nid} -> {child_nid};\n")

        outfile.write("}\n")
    finally:
        if output:
            outfile.close()
