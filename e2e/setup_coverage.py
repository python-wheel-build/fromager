#!/usr/bin/env python3
"""Simple coverage setup for E2E tests."""

import pathlib
import sys
import site

def setup_coverage():
    """Create coverage.pth file for subprocess coverage collection."""
    # Get the virtual environment root
    venv_root = pathlib.Path(sys.prefix)
    
    # Find site-packages directory
    site_packages_dirs = [pathlib.Path(p) for p in site.getsitepackages()]
    
    # Find the one that's in our virtual environment
    site_packages = None
    for sp in site_packages_dirs:
        if str(sp).startswith(str(venv_root)):
            site_packages = sp
            break
    
    if not site_packages:
        site_packages = site_packages_dirs[0]  # fallback
    
    # Create coverage.pth file
    cov_pth = site_packages / "cov.pth"
    cov_pth.parent.mkdir(parents=True, exist_ok=True)
    cov_pth.write_text("import coverage; coverage.process_startup()")
    
    print(f"Coverage setup complete: {cov_pth}")

if __name__ == "__main__":
    setup_coverage() 
