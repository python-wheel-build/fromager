from importlib import metadata

from sphinx.addnodes import desc_signature
from sphinx.application import Sphinx
from sphinx.domains.python import PyFunction
from sphinx.ext.autodoc import FunctionDocumenter
from sphinx.util.typing import ExtensionMetadata

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "Fromager"
copyright = "2024, Fromager Authors"
author = "Fromager Authors"
release = metadata.version("fromager")

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx_click",
    "myst_parser",
    "sphinxcontrib.autodoc_pydantic",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
]

# Recognized suffixes
source_suffix = [
    ".rst",
    ".md",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

language = "English"

# references to Python stdlib and packaging
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "packaging": ("https://packaging.pypa.io/en/stable/", None),
    "pyproject-hooks": ("https://pyproject-hooks.readthedocs.io/en/latest/", None),
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

suppress_warnings = [
    "ref",  # autodoc generates a lot of warnings for missing classes that we do not want to include
]
autodoc_pydantic_model_show_json = False
autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_model_show_validator_summary = False
autodoc_pydantic_model_show_validator_members = False

# autodoc_typehints_format = "fully-qualified"


class FromagerHookDocumenter(FunctionDocumenter):
    """Documenter for 'autofromagehook' directive"""

    objtype = "fromagerhook"

    def format_name(self):
        name = super().format_name()
        if name.startswith("default_"):
            name = name[8:]
        return name


class PyFromagerHook(PyFunction):
    """:py:fromagehook"""

    def handle_signature(self, sig: str, signode: desc_signature) -> tuple[str, str]:
        # hack to remove module prefix from output
        self.options["module"] = None
        return super().handle_signature(sig, signode)


def setup(app: Sphinx) -> ExtensionMetadata:
    app.setup_extension("sphinx.ext.autodoc")
    app.add_directive_to_domain("py", FromagerHookDocumenter.objtype, PyFromagerHook)
    app.add_autodocumenter(FromagerHookDocumenter)

    return {"version": release, "parallel_read_safe": True}
