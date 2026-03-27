"""Setup script that intentionally fails during build."""
import sys

# Fail immediately when this module is imported during build
raise RuntimeError("Intentional build failure for e2e testing")
