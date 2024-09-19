"""Update bundled wheels"""

import subprocess

from .seeder import BUNDLED_DIR, BUNDLED_PACKAGES


def main():
    for whl in BUNDLED_DIR.glob("*.whl"):
        whl.unlink()
    cmd = ["pip", "download", "-d", str(BUNDLED_DIR), *BUNDLED_PACKAGES]
    subprocess.check_call(cmd)


if __name__ == "__main__":
    main()
