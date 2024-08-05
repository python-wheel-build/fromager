from importlib import metadata

from sphinx.addnodes import pending_xref
from sphinx.transforms import SphinxTransform

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "Fromager"
copyright = "2024, Doug Hellmann"
author = "Doug Hellmann"
release = metadata.version("fromager")

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = ["sphinx_click", "myst_parser"]

# Recognized suffixes
source_suffix = [
    ".rst",
    ".md",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

language = "English"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "alabaster"
html_static_path = ["_static"]


class RootReadmeTransform(SphinxTransform):
    default_priority = 1

    def apply(self, **kwargs) -> None:
        for node in self.document.traverse(pending_xref):
            if node.source == "../README.md":
                reftarget = node.get("reftarget")
                if reftarget is not None and reftarget.startswith("docs/"):
                    # remove `docs/` and `.md`
                    node["reftarget"] = reftarget[5:-3]


def setup(app):
    app.add_transform(RootReadmeTransform)
