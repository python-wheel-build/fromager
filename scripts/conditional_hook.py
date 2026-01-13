#!/usr/bin/env python3
"""Conditional Pre-commit Hook Wrapper.

Wraps pre-commit hook commands to allow conditional execution based on:
1. Execution context (CI vs Local)
2. Availability of runtime dependencies

Design:
- In CI: Strict enforcement. Missing tools = configuration error (exit 1)
- Locally: Graceful degradation. Missing tools = warning + skip (exit 0)

Usage:
    python scripts/conditional_hook.py <executable> [args...]

Examples:
    python scripts/conditional_hook.py markdownlint --config .markdownlint.yaml .
    python scripts/conditional_hook.py npx markdownlint-cli2 "**/*.md"
"""

import os
import shutil
import subprocess
import sys
from typing import NoReturn

# Environment variables that indicate CI environment
# Covers: GitHub Actions, GitLab CI, Travis, Jenkins, Azure Pipelines, CircleCI
CI_ENV_VARS = frozenset(
    {
        "CI",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "TRAVIS",
        "JENKINS_URL",
        "TF_BUILD",
        "CIRCLECI",
        "BUILDKITE",
        "CODEBUILD_BUILD_ID",  # AWS CodeBuild
    }
)


def is_ci() -> bool:
    """Detect if running in a CI environment."""
    return any(os.environ.get(var) for var in CI_ENV_VARS)


def supports_color() -> bool:
    """Check if terminal supports color output."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


def format_message(prefix: str, message: str, color_code: str) -> str:
    """Format a message with optional color."""
    if supports_color():
        reset = "\033[0m"
        bold = "\033[1m"
        return f"{color_code}{bold}{prefix}{reset} {color_code}{message}{reset}"
    return f"{prefix} {message}"


def print_warning(message: str) -> None:
    """Print a warning message (yellow)."""
    yellow = "\033[33m"
    print(format_message("⚠️  SKIPPED:", message, yellow), file=sys.stderr)


def print_error(message: str) -> None:
    """Print an error message (red)."""
    red = "\033[31m"
    print(format_message("❌ CI ERROR:", message, red), file=sys.stderr)


def print_info(message: str) -> None:
    """Print an info message (for verbose output)."""
    print(f"   {message}", file=sys.stderr)


def find_executable(name: str) -> str | None:
    """Find an executable in PATH."""
    return shutil.which(name)


def run_tool(executable: str, args: list[str]) -> int:
    """Run the tool and return its exit code."""
    cmd = [executable, *args]
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except FileNotFoundError:
        print_error(f"Executable '{executable}' not found during execution")
        return 1
    except PermissionError:
        print_error(f"Permission denied executing '{executable}'")
        return 1
    except Exception as e:
        print_error(f"Failed to execute '{executable}': {e}")
        return 1


def main() -> NoReturn:
    """Main entry point."""
    if len(sys.argv) < 2:
        print(
            "Usage: python conditional_hook.py <executable> [args...] [files...]",
            file=sys.stderr,
        )
        print("\nExample:", file=sys.stderr)
        print(
            "  python conditional_hook.py markdownlint --config .markdownlint.yaml",
            file=sys.stderr,
        )
        sys.exit(2)

    executable = sys.argv[1]
    args = sys.argv[2:]
    exe_path = find_executable(executable)

    if not exe_path:
        if is_ci():
            print_error(
                f"Required executable '{executable}' not found in CI environment."
            )
            print_info("Ensure the CI workflow installs all required dependencies.")
            print_info("For Node.js tools: actions/setup-node + npm install -g <tool>")
            sys.exit(1)
        else:
            if "markdownlint" in executable:
                print_warning("markdownlint requires Node.js (skipping)")
                print_info("To enable: Install Node.js, then run:")
                print_info("  npm install -g markdownlint-cli2")
            else:
                print_warning(f"'{executable}' is not installed (skipping)")
                print_info(f"Install '{executable}' and ensure it's in your PATH")
            sys.exit(0)

    exit_code = run_tool(exe_path, args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
