#!/usr/bin/env bash
#
# Setup script to install the pre-commit hook for fromager development
#
# This script copies the pre-commit hook to .git/hooks/ and makes it executable
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"
PRE_COMMIT_HOOK="$HOOKS_DIR/pre-commit"

echo "🔧 Setting up pre-commit hook for fromager..."

# Check if we're in a git repository
if [ ! -d "$HOOKS_DIR" ]; then
    echo "❌ Error: Not in a git repository or .git/hooks directory not found"
    exit 1
fi

# Copy the pre-commit hook script
cp "$SCRIPT_DIR/pre-commit" "$PRE_COMMIT_HOOK"

# Make it executable
chmod +x "$PRE_COMMIT_HOOK"

echo "✅ Pre-commit hook installed successfully!"
echo ""
echo "The hook will now run 'hatch run lint:check' and 'hatch run mypy:check'"
echo "before every commit to ensure code quality."
echo ""
echo "To bypass the hook for a specific commit (not recommended):"
echo "  git commit --no-verify -m \"message\""