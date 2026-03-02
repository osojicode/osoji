"""Git hook management for automatic shadow doc updates."""

import stat
import subprocess
from pathlib import Path
from typing import Optional


# Hook templates
PRE_COMMIT_HOOK = '''#!/bin/sh
# Docstar pre-commit hook: Safety + Documentation quality gate
# Installed by: docstar hooks install

REPO_ROOT=$(git rev-parse --show-toplevel)

# Load environment variables from .env files (for API keys, etc.)
# Priority: repo .env > user config > global config
[ -f "$HOME/.config/docstar/env" ] && export $(grep -v '^#' "$HOME/.config/docstar/env" | xargs)
[ -f "$REPO_ROOT/.env" ] && export $(grep -v '^#' "$REPO_ROOT/.env" | xargs)

# Find docstar - check PATH first, then common locations
DOCSTAR=""
if command -v docstar &> /dev/null; then
    DOCSTAR="docstar"
elif [ -x "$HOME/.local/bin/docstar" ]; then
    DOCSTAR="$HOME/.local/bin/docstar"
elif [ -x "/usr/local/bin/docstar" ]; then
    DOCSTAR="/usr/local/bin/docstar"
fi

if [ -z "$DOCSTAR" ]; then
    echo "Warning: docstar not found, skipping checks"
    exit 0
fi

cd "$REPO_ROOT"

# Step 1: Safety check (personal paths + secrets)
echo "Docstar: Running safety check..."
"$DOCSTAR" safety check

SAFETY_RESULT=$?

if [ $SAFETY_RESULT -ne 0 ]; then
    echo ""
    echo "Commit blocked by safety check."
    echo "Review the findings above and fix before committing."
    exit 1
fi

# Step 2: Mark stale shadow docs (fast, no LLM calls)
echo ""
echo "Docstar: Checking shadow documentation freshness..."
echo ""

"$DOCSTAR" check .

# Stage any updated shadow docs and staleness manifest
SHADOW_DIR=".docstar/shadow"
if [ -d "$SHADOW_DIR" ]; then
    git add "$SHADOW_DIR" 2>/dev/null || true
fi
if [ -f ".docstar/staleness.json" ]; then
    git add ".docstar/staleness.json" 2>/dev/null || true
fi

exit 0
'''


POST_COMMIT_HOOK = '''#!/bin/sh
# Docstar post-commit hook: Update shadow docs after commit
# Installed by: docstar hooks install

# Get the root of the git repository
REPO_ROOT=$(git rev-parse --show-toplevel)

# Check if docstar is available
if ! command -v docstar &> /dev/null; then
    exit 0
fi

# Run docstar check to see if any updates are needed
cd "$REPO_ROOT"
ISSUES=$(docstar check . 2>&1 | grep -c "\\[")

if [ "$ISSUES" -gt 0 ]; then
    echo ""
    echo "Docstar: Shadow documentation may need updating."
    echo "Run 'docstar shadow .' to regenerate."
fi

exit 0
'''


PRE_PUSH_HOOK = '''#!/bin/sh
# Docstar pre-push hook: Warn about stale shadow docs
# Installed by: docstar hooks install

# Get the root of the git repository
REPO_ROOT=$(git rev-parse --show-toplevel)

# Check if docstar is available
if ! command -v docstar &> /dev/null; then
    exit 0
fi

cd "$REPO_ROOT"
ISSUES=$(docstar check . 2>&1)
ISSUE_COUNT=$(echo "$ISSUES" | grep -c "\\[" || true)

if [ "$ISSUE_COUNT" -gt 0 ]; then
    echo ""
    echo "⚠ Docstar: Found stale or missing shadow documentation:"
    echo "$ISSUES" | grep "\\["
    echo ""
    echo "Consider running 'docstar shadow .' before pushing."
    echo ""
fi

# Don't block push, just warn
exit 0
'''


def find_git_root(start_path: Path) -> Optional[Path]:
    """Find the .git directory starting from a path."""
    current = start_path.resolve()
    while current != current.parent:
        git_dir = current / ".git"
        if git_dir.is_dir():
            return current
        current = current.parent
    return None


def get_hooks_dir(repo_root: Path) -> Path:
    """Get the git hooks directory."""
    return repo_root / ".git" / "hooks"


def install_hook(hooks_dir: Path, hook_name: str, content: str, force: bool = False) -> tuple[bool, str]:
    """Install a git hook.
    
    Returns (success, message).
    """
    hook_path = hooks_dir / hook_name
    
    # Check if hook already exists
    if hook_path.exists() and not force:
        existing = hook_path.read_text(encoding="utf-8")
        if "docstar" in existing.lower():
            return (True, f"{hook_name}: already installed (use --force to reinstall)")
        else:
            return (False, f"{hook_name}: existing hook found (use --force to overwrite)")
    
    # Write the hook
    hook_path.write_text(content, encoding="utf-8")
    
    # Make executable (Unix)
    try:
        current_mode = hook_path.stat().st_mode
        hook_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass  # Windows doesn't need this
    
    return (True, f"{hook_name}: installed")


def uninstall_hook(hooks_dir: Path, hook_name: str) -> tuple[bool, str]:
    """Uninstall a docstar git hook.
    
    Only removes if it's a docstar-installed hook.
    Returns (success, message).
    """
    hook_path = hooks_dir / hook_name
    
    if not hook_path.exists():
        return (True, f"{hook_name}: not installed")
    
    content = hook_path.read_text(encoding="utf-8")
    if "docstar" not in content.lower():
        return (False, f"{hook_name}: not a docstar hook, skipping")
    
    hook_path.unlink()
    return (True, f"{hook_name}: removed")


def install_hooks(
    repo_path: Path,
    pre_commit: bool = True,
    post_commit: bool = False,
    pre_push: bool = True,
    force: bool = False,
) -> list[tuple[str, bool, str]]:
    """Install docstar git hooks.
    
    Returns list of (hook_name, success, message) tuples.
    """
    git_root = find_git_root(repo_path)
    if git_root is None:
        return [("git", False, "Not a git repository")]
    
    hooks_dir = get_hooks_dir(git_root)
    if not hooks_dir.exists():
        hooks_dir.mkdir(parents=True)
    
    results: list[tuple[str, bool, str]] = []
    
    if pre_commit:
        success, msg = install_hook(hooks_dir, "pre-commit", PRE_COMMIT_HOOK, force)
        results.append(("pre-commit", success, msg))
    
    if post_commit:
        success, msg = install_hook(hooks_dir, "post-commit", POST_COMMIT_HOOK, force)
        results.append(("post-commit", success, msg))
    
    if pre_push:
        success, msg = install_hook(hooks_dir, "pre-push", PRE_PUSH_HOOK, force)
        results.append(("pre-push", success, msg))
    
    return results


def uninstall_hooks(repo_path: Path) -> list[tuple[str, bool, str]]:
    """Uninstall all docstar git hooks.
    
    Returns list of (hook_name, success, message) tuples.
    """
    git_root = find_git_root(repo_path)
    if git_root is None:
        return [("git", False, "Not a git repository")]
    
    hooks_dir = get_hooks_dir(git_root)
    if not hooks_dir.exists():
        return [("hooks", True, "No hooks directory")]
    
    results: list[tuple[str, bool, str]] = []
    
    for hook_name in ["pre-commit", "post-commit", "pre-push"]:
        success, msg = uninstall_hook(hooks_dir, hook_name)
        results.append((hook_name, success, msg))
    
    return results



def get_staged_files_all(repo_path: Path) -> list[Path]:
    """Get list of all staged files without extension filtering.

    Returns all staged files regardless of extension, for use by safety checks.

    Args:
        repo_path: Path to the repository

    Returns:
        List of absolute paths to staged files
    """
    git_root = find_git_root(repo_path)
    if git_root is None:
        return []

    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=git_root,
            capture_output=True,
            text=True,
            check=True,
        )

        files: list[Path] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            path = git_root / line
            if path.exists():
                files.append(path)

        return files
    except subprocess.CalledProcessError:
        return []
