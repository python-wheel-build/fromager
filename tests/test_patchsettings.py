import pydantic
import yaml

from fromager.packagesettings import MODEL_CONFIG
from fromager.packagesettings._patch import Patches

# example from new patcher proposal
EXAMPLE = """
patch:
  - title: Comment out 'foo' requirement for version >= 1.2
    op: replace-line
    files:
      - 'requirements.txt'
    search: '^(foo.*)$'
    replace: '# \\1'
    when_version: '>=1.2'
    ignore_missing: true

  - title: Remove 'bar' from constraints.txt
    op: delete-line
    files:
      - 'constraints.txt'
    search: 'bar.*'

  - title: Fix PKG-INFO metadata version
    op: fix-pkg-info
    metadata_version: '2.4'
    when_version: '<1.0'

  - title: Add missing setuptools to pyproject.toml
    op: pyproject-build-system
    update_build_requires:
      - setuptools

  - title: Update Torch install requirement to version in build env
    op: pin-requires-dist-to-constraint
    requirements:
     - torch
"""


def test_patch_settings_basics() -> None:
    # temporary test case until patch settings are hooked up to PBI

    class Settings(pydantic.BaseModel):
        model_config = MODEL_CONFIG
        patch: Patches

    settings = Settings(**yaml.safe_load(EXAMPLE))
    patchers = settings.patch.root
    assert len(patchers) == 5
