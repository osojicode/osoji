# Protecting Your Repository with Safety Checks

This tutorial walks you through setting up Osoji's safety checking system,
seeing it catch real problems, and integrating it into your development
workflow with git hooks.

**Time estimate**: 15-20 minutes.

**Prerequisites**:

- Osoji installed (`pip install osojicode`).
- A git repository to work in (can be a throwaway test repo).
- Optional: `pip install 'osojicode[safety]'` for secret detection via
  `detect-secrets`.

---

## Understanding the risks

Developers accidentally commit two categories of sensitive information:

1. **Personal filesystem paths** -- Paths like `/Users/jsmith/projects/myapp`
   or `C:\Users\alice\Documents\work` reveal usernames and directory
   structures. They also create machine-specific dependencies that break
   portability.

2. **Secrets** -- API keys, tokens, passwords, and private keys embedded in
   source code. Once committed and pushed, these are extremely difficult to
   fully remove from git history.

Both types of leaks are easy to introduce (a quick print statement for
debugging, a hardcoded path in a config file) and hard to notice during code
review. Osoji's safety checks automate the detection so you catch these before
they enter your repository.

---

## Step 1: Run your first safety check

Start in a clean git repository. If you do not have one:

```bash
mkdir safety-demo && cd safety-demo
git init
```

Run the safety check with no staged files:

```bash
osoji safety check
```

Output:

```
Safety check passed - no issues found.
```

With no files staged, there is nothing to check. The check passes immediately.

### Checking specific files

You can also check specific files directly, regardless of whether they are
staged:

```bash
osoji safety check README.md
osoji safety check src/*.py
```

---

## Step 2: View detection patterns

Before creating test violations, see what Osoji looks for:

```bash
osoji safety patterns
```

Output:

```
Personal Path Patterns
==================================================

[windows_user]
  Description: Windows user directory (C:\Users\username\)
  Regex: [Cc]:[\\\/]Users[\\\/](?!test[\\\/]|user[\\\/]|example[\\\/]|runner[\\\/])[a-zA-Z0-9._-]+[\\\/]

[unix_home]
  Description: Unix/Mac home directory (/home/username/ or /Users/username/)
  Regex: /(?:Users|home)/(?!test/|user/|example/|runner/|ubuntu/)[a-zA-Z0-9._-]+/

[cloud_storage]
  Description: Cloud storage path (Dropbox, OneDrive, Google Drive, iCloud, Box, pCloud)
  Regex: [\\\/](?:Dropbox|OneDrive|Google\s*Drive|iCloud|Box|pCloud)[\\\/][^\\\/]+[\\\/]

[dated_folder]
  Description: Dated project folder (e.g., /260124 MYPROJECT/)
  Regex: [\\\/]\d{6}\s+[A-Z]+[\\\/]

[personal_folder]
  Description: Personal folder (Documents, Desktop, Downloads, Pictures, Videos)
  Regex: [\\\/](?:Documents|Desktop|Downloads|Pictures|Videos)[\\\/][^\\\/]+[\\\/]

[my_folder]
  Description: "My X" folder pattern (My Projects, My Documents, etc.)
  Regex: [\\\/]My\s+[A-Za-z0-9]+[\\\/]

--------------------------------------------------
Total: 6 patterns

detect-secrets: not installed
  Install with: pip install 'osoji[safety]'
```

### Pattern details

Each pattern is a compiled regex designed to catch personal paths while
excluding generic paths used in CI environments and test fixtures:

| Pattern | Catches | Excludes |
|---------|---------|----------|
| `windows_user` | `C:\Users\jsmith\`, `c:/Users/alice/` | `C:\Users\test\`, `C:\Users\runner\`, `C:\Users\example\` |
| `unix_home` | `/home/jsmith/`, `/Users/alice/` | `/home/test/`, `/Users/runner/`, `/home/ubuntu/` |
| `cloud_storage` | `/Dropbox/projects/`, `\OneDrive\Documents\` | (none) |
| `dated_folder` | `/260124 MYPROJECT/`, `\251007 FIXTHEDOCS\` | (none) |
| `personal_folder` | `/Documents/work/`, `/Desktop/project/` | (none) |
| `my_folder` | `/My Projects/`, `\My Documents\` | (none) |

The exclusions (`test`, `user`, `example`, `runner`, `ubuntu`) prevent false
positives in CI environments and test fixtures where generic usernames are
expected.

### Secret detection status

The last line shows whether `detect-secrets` is installed. If not, secret
detection is skipped (only path detection runs). To enable it:

```bash
pip install 'osojicode[safety]'
```

After installation, `osoji safety patterns` shows:

```
detect-secrets: installed (secrets will be checked)
```

---

## Step 3: Create a test violation (personal path)

Create a file with a personal filesystem path:

```bash
cat > test_config.py <<'EOF'
# Application configuration

DATA_DIR = "/Users/johndoe/projects/myapp/data"
LOG_DIR = "/home/johndoe/logs/myapp"
BACKUP_DIR = "C:\\Users\\johndoe\\Documents\\backups"
EOF
```

Stage it:

```bash
git add test_config.py
```

Run the safety check:

```bash
osoji safety check
```

Output:

```
Safety check FAILED

## Personal Paths Found (3)

**test_config.py**
  Line 3: `/Users/johndoe/projects/`
    Pattern: unix_home
  Line 4: `/home/johndoe/`
    Pattern: unix_home
  Line 5: `C:\Users\johndoe\Documents\`
    Pattern: windows_user

---

Replace personal paths with generic alternatives:
  - /path/to/project
  - ~/workspace/project
  - ./relative/path

To bypass in emergencies: git commit --no-verify

---
Total: 3 issue(s) in 1 file(s)
```

### Understanding the output

Each finding shows:

- **File**: The file containing the violation.
- **Line number**: Where in the file the path was found.
- **Match**: The specific path fragment that triggered the pattern.
- **Pattern name**: Which regex pattern matched (`unix_home`, `windows_user`,
  `cloud_storage`, `dated_folder`, `personal_folder`, `my_folder`).

The remediation section suggests generic replacement paths.

The exit code is `1` (failure), which is what blocks a commit when used as a
git hook.

### Verbose output

For more detail including files checked and skipped:

```bash
osoji --verbose safety check
```

This adds:

```
  Files checked: 1
  Files skipped: 0
```

### Verification checkpoint

1. `osoji safety check` exits with code 1 (failure).
2. The output lists all three personal paths with correct line numbers.
3. Each finding shows the pattern name that matched.

---

## Step 4: Create a test violation (secret)

If you have `detect-secrets` installed, add a line that looks like an API key:

```bash
cat >> test_config.py <<'EOF'

# API credentials
OPENAI_KEY = "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"
AWS_SECRET = "AKIAIOSFODNN7EXAMPLE"
EOF
```

Stage the updated file:

```bash
git add test_config.py
```

Run the safety check:

```bash
osoji safety check
```

Output (with detect-secrets installed):

```
Safety check FAILED

## Personal Paths Found (3)

**test_config.py**
  Line 3: `/Users/johndoe/projects/`
    Pattern: unix_home
  Line 4: `/home/johndoe/`
    Pattern: unix_home
  Line 5: `C:\Users\johndoe\Documents\`
    Pattern: windows_user

## Potential Secrets Found (2)

**test_config.py**
  Line 8: Secret Keyword
  Line 9: AWS Access Key

---

Replace personal paths with generic alternatives:
  - /path/to/project
  - ~/workspace/project
  - ./relative/path

Move secrets to environment variables.

To bypass in emergencies: git commit --no-verify

---
Total: 5 issue(s) in 1 file(s)
```

Secret findings show the line number and the type of secret detected (e.g.,
"Secret Keyword", "AWS Access Key"). The actual secret value is not printed
in the output.

If `detect-secrets` is not installed, only the personal path findings appear.
The secret detection is silently skipped.

---

## Step 5: Check specific files

You can check files that are not staged by passing them as arguments:

```bash
osoji safety check test_config.py
```

This checks the specified file directly, regardless of its git staging status.
Useful for checking files before staging them.

You can also use glob patterns:

```bash
osoji safety check src/*.py docs/*.md
```

### File filtering

Osoji automatically skips certain files and directories:

**Checked extensions**: `.py`, `.pyi`, `.js`, `.ts`, `.jsx`, `.tsx`, `.json`, `.yaml`,
`.yml`, `.toml`, `.ini`, `.cfg`, `.md`, `.txt`, `.rst`, `.sh`, `.bash`,
`.zsh`, `.env`, `.sql`, `.xml`, `.html`, `.htm`

**Skipped binary extensions**: `.jpg`, `.png`, `.pdf`, `.zip`, `.exe`, `.dll`,
`.pyc`, `.whl`, `.db`, `.lock`, and many more.

**Skipped directories**: `.git`, `__pycache__`, `node_modules`, `venv`,
`.venv`, `build`, `dist`, `.osoji`, and other common build/cache directories.

Files with no extension (like `Makefile`, `Dockerfile`) are checked by
default.

---

## Step 6: Run the self-test

The self-test verifies that Osoji's own source code does not contain personal
paths:

```bash
osoji safety self-test
```

Output:

```
Scanning /path/to/site-packages/osoji...
Safety check passed - no issues found.
  Files checked: 25
  Files skipped: 2

Self-test passed: No personal paths found in osoji package.
```

This command:

1. Scans all Python files in the installed `osoji` package (except
   `paths.py`, which contains example paths in its documentation and has its
   own specialized self-test).
2. Runs the `paths.py` module self-test, which filters out matches in
   comments, docstrings, and pattern descriptions.
3. Reports combined results.

The self-test is useful for:

- Verifying that an Osoji installation is clean.
- Running in CI to ensure no personal paths were accidentally committed to
  the Osoji codebase itself.
- Sanity-checking after modifying the safety module.

---

## Step 7: Install git hooks

The most effective way to use safety checks is as a git pre-commit hook. This
automatically blocks commits that contain personal paths or secrets.

### Install the hooks

```bash
osoji hooks install
```

Output:

```
  [ok] pre-commit: installed
  [ok] pre-push: installed

Hooks installed successfully.
Shadow docs will be updated automatically on commit.
```

By default, two hooks are installed:

| Hook | Behavior |
|------|----------|
| **pre-commit** | Runs `osoji safety check` (blocks on failure) then `osoji check .` (marks stale docs, non-blocking). |
| **pre-push** | Warns about stale shadow documentation before push (non-blocking). |

### What the pre-commit hook does

The pre-commit hook script:

1. **Finds the repository root** using `git rev-parse --show-toplevel`.
2. **Loads environment variables** from `~/.config/osoji/env` and the
   project's `.env` file (for API keys needed by `osoji check`).
3. **Runs `osoji safety check`**. If findings are found, the commit is
   **blocked** with exit code 1.
4. **Runs `osoji check .`**. This marks stale shadow docs but does **not**
   block the commit.
5. **Stages updated shadow docs** and the staleness manifest so they are
   included in the commit.

### Selective hook installation

Install only specific hooks:

```bash
# Pre-commit only (no pre-push)
osoji hooks install --no-pre-push

# Post-commit only (no pre-commit, no pre-push)
osoji hooks install --no-pre-commit --no-pre-push --post-commit

# Pre-commit and post-commit (no pre-push)
osoji hooks install --no-pre-push --post-commit
```

The post-commit hook (off by default) reminds you to update shadow docs
after committing.

### Force reinstall

If hooks already exist:

```bash
osoji hooks install --force
```

This overwrites existing hooks. Without `--force`, Osoji skips hooks that
already exist (whether Osoji-installed or not).

---

## Step 8: See the hook block a commit

With the pre-commit hook installed and the test file still staged, try to
commit:

```bash
git commit -m "Add configuration"
```

The hook runs and blocks the commit:

```
Osoji: Running safety check...
Safety check FAILED

## Personal Paths Found (3)

**test_config.py**
  Line 3: `/Users/johndoe/projects/`
    Pattern: unix_home
  Line 4: `/home/johndoe/`
    Pattern: unix_home
  Line 5: `C:\Users\johndoe\Documents\`
    Pattern: windows_user

## Potential Secrets Found (2)

**test_config.py**
  Line 8: Secret Keyword
  Line 9: AWS Access Key

---

Replace personal paths with generic alternatives:
  - /path/to/project
  - ~/workspace/project
  - ./relative/path

Move secrets to environment variables.

To bypass in emergencies: git commit --no-verify

---
Total: 5 issue(s) in 1 file(s)

Commit blocked by safety check.
Review the findings above and fix before committing.
```

The commit did not happen. Your repository is protected.

### Verification checkpoint

1. The commit was blocked (you see "Commit blocked by safety check").
2. `git log` does not show a new commit.
3. The staged file with violations is still staged (`git status` shows it).

---

## Step 9: Fix and commit successfully

Replace the personal paths with generic alternatives and remove the secrets:

```bash
cat > test_config.py <<'EOF'
import os

# Application configuration
DATA_DIR = os.environ.get("DATA_DIR", "./data")
LOG_DIR = os.environ.get("LOG_DIR", "./logs")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backups")

# API credentials loaded from environment
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
AWS_SECRET = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
EOF
```

Stage the fixed file:

```bash
git add test_config.py
```

Verify the fix:

```bash
osoji safety check
```

Output:

```
Safety check passed - no issues found.
```

Now commit:

```bash
git commit -m "Add configuration using environment variables"
```

The pre-commit hook runs, passes, and the commit succeeds:

```
Osoji: Running safety check...
Safety check passed - no issues found.

Osoji: Checking shadow documentation freshness...

All shadow documentation is up to date.
[main abc1234] Add configuration using environment variables
 1 file changed, 10 insertions(+)
 create mode 100644 test_config.py
```

### Verification checkpoint

1. `osoji safety check` passes (exit code 0).
2. The commit succeeds.
3. `git log --oneline -1` shows the new commit.

---

## Step 10: Clean up

### Remove test files

```bash
git rm test_config.py
git commit -m "Remove test configuration"
```

### Uninstall hooks (optional)

If you want to remove the Osoji hooks:

```bash
osoji hooks uninstall
```

Output:

```
  [ok] pre-commit: removed
  [ok] post-commit: not installed
  [ok] pre-push: removed
```

Only Osoji-installed hooks are removed. If a hook exists but was not installed
by Osoji (the script does not contain "osoji"), it is skipped:

```
  [FAIL] pre-commit: not a osoji hook, skipping
```

---

## How safety checks integrate with the audit

Safety checks and audits serve different purposes but work together:

| Feature | Purpose | When it runs |
|---------|---------|--------------|
| `osoji safety check` | Block commits with personal paths / secrets | Pre-commit hook, manual |
| `osoji audit .` | Assess documentation quality and code hygiene | Manual, CI pipeline |
| `osoji check .` | Mark stale shadow docs | Pre-commit hook, manual |

The pre-commit hook installed by `osoji hooks install` runs both `osoji safety
check` (blocking) and `osoji check .` (non-blocking). This gives you:

- **Immediate protection**: Personal paths and secrets never enter git history.
- **Awareness**: Stale shadow docs are marked so you know to regenerate before
  auditing.

For full CI integration, you would also run `osoji audit .` in your CI
pipeline. This is covered in the CI/CD how-to guide.

---

## Supported file types for safety checking

The safety module checks files based on their extension. Here is the complete
list of checked extensions:

| Category | Extensions |
|----------|-----------|
| Python | `.py`, `.pyi` |
| JavaScript/TypeScript | `.js`, `.ts`, `.mjs`, `.jsx`, `.tsx` |
| Configuration | `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg` |
| Documentation | `.md`, `.txt`, `.rst` |
| Shell | `.sh`, `.bash`, `.zsh` |
| Environment | `.env` (files named `.env`, `.env.local`, etc. are also checked) |
| Database | `.sql` |
| Markup | `.xml`, `.html`, `.htm` |
| No extension | Checked by default (Makefile, Dockerfile, etc.) |

Binary files (images, archives, executables, compiled files) and files in
skip directories (`.git`, `node_modules`, `__pycache__`, `venv`, etc.) are
automatically excluded.

---

## Common scenarios and edge cases

### Scenario: Cloud storage paths

If you use Dropbox, OneDrive, or Google Drive to sync your projects, the
absolute path to your repository likely contains a cloud storage path. These
are caught by the `cloud_storage` pattern:

```python
# This will be caught:
PROJECT_ROOT = "/Users/alice/Dropbox/projects/myapp/"
BACKUP = "C:\\Users\\bob\\OneDrive\\Documents\\backups\\"
```

Fix by using relative paths or environment variables:

```python
# Fixed:
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.environ.get("BACKUP_DIR", "./backups")
```

### Scenario: Dated project folders

Some developers organize projects with dated prefixes (e.g., `260301 MYPROJECT`).
The `dated_folder` pattern catches these:

```python
# This will be caught (6 digits + space + UPPERCASE):
CONFIG_PATH = "/home/dev/260301 MYPROJECT/config.json"
```

### Scenario: Documentation examples

Documentation files may contain example paths for illustration. These are
caught by the patterns since the safety check does not distinguish between
documentation and code. If you have a README explaining installation paths,
you have several options:

1. Use generic paths that match the pattern exclusions (`/Users/test/`,
   `/home/example/`).
2. Use obviously placeholder paths (`/path/to/project`).
3. Override with `git commit --no-verify` after manual review.

### Scenario: `.env` files

The `.env` extension has special handling. In the file filtering logic, a file
named `.env`, `.env.local`, `.env.production`, etc. is always checked,
regardless of directory skip rules. This is critical because `.env` files
frequently contain secrets.

If your `.env` file is properly gitignored, it will not be staged and
therefore will not be checked by `osoji safety check` in its default
(staged-files) mode. But if you explicitly check it:

```bash
osoji safety check .env
```

Osoji will scan it and report any secrets found (if `detect-secrets` is
installed).

### Scenario: False positives in test fixtures

Test files under a `safety/` directory (files matching `test_*.py` or
`paths.py` inside a `safety/` directory) are automatically skipped during
safety checks. This prevents circular blocking when the test suite
intentionally contains example personal paths to test detection.

---

## The CheckResult data model

Understanding the data model helps when integrating safety checks into
custom tooling. The safety module exports these types:

### `PathFinding`

Represents a detected personal path:

```python
@dataclass
class PathFinding:
    file: Path          # Path to the file containing the finding
    line_number: int    # Line number (1-based)
    line_content: str   # Full content of the line (stripped)
    pattern_name: str   # Which pattern matched (e.g., "unix_home")
    match: str          # The specific substring that matched
```

### `SecretFinding`

Represents a detected potential secret:

```python
@dataclass
class SecretFinding:
    file: Path          # Path to the file
    line_number: int    # Line number (1-based)
    secret_type: str    # Type of secret (e.g., "AWS Access Key")
```

### `CheckResult`

Combined result for one or more files:

```python
@dataclass
class CheckResult:
    path_findings: list[PathFinding]
    secret_findings: list[SecretFinding]
    files_checked: int
    files_skipped: int
    errors: list[str]

    @property
    def passed(self) -> bool:
        return not self.path_findings and not self.secret_findings

    @property
    def finding_count(self) -> int:
        return len(self.path_findings) + len(self.secret_findings)
```

The `passed` property returns `True` only when both `path_findings` and
`secret_findings` are empty. Any finding of either type causes failure.

Multiple `CheckResult` instances can be merged with the `merge()` method,
which concatenates findings and sums file counts.

---

## Hook script anatomy

The pre-commit hook installed by `osoji hooks install` is a shell script.
Understanding its structure helps when debugging hook behavior:

```bash
#!/bin/sh
# Osoji pre-commit hook: Safety + Documentation quality gate

REPO_ROOT=$(git rev-parse --show-toplevel)

# Load environment variables from .env files
[ -f "$HOME/.config/osoji/env" ] && set -a && . "$HOME/.config/osoji/env" && set +a
[ -f "$REPO_ROOT/.env" ] && set -a && . "$REPO_ROOT/.env" && set +a

# Find osoji - check PATH first, then common locations
OSOJI=""
if command -v osoji &> /dev/null; then
    OSOJI="osoji"
elif [ -x "$HOME/.local/bin/osoji" ]; then
    OSOJI="$HOME/.local/bin/osoji"
elif [ -x "/usr/local/bin/osoji" ]; then
    OSOJI="/usr/local/bin/osoji"
fi

if [ -z "$OSOJI" ]; then
    echo "Warning: osoji not found, skipping checks"
    exit 0
fi

cd "$REPO_ROOT"

# Step 1: Safety check (blocks on failure)
echo "Osoji: Running safety check..."
"$OSOJI" safety check
SAFETY_RESULT=$?
if [ $SAFETY_RESULT -ne 0 ]; then
    echo ""
    echo "Commit blocked by safety check."
    exit 1
fi

# Step 2: Mark stale shadow docs (non-blocking)
echo ""
echo "Osoji: Checking shadow documentation freshness..."
"$OSOJI" check .

# Stage updated shadow docs
SHADOW_DIR=".osoji/shadow"
if [ -d "$SHADOW_DIR" ]; then
    git add "$SHADOW_DIR" 2>/dev/null || true
fi
if [ -f ".osoji/staleness.json" ]; then
    git add ".osoji/staleness.json" 2>/dev/null || true
fi

exit 0
```

Key behaviors:

1. **Graceful degradation**: If `osoji` is not found on PATH, the hook exits
   successfully (does not block).
2. **Environment loading**: Loads `.env` files for API keys needed by
   `osoji check`.
3. **Two-step process**: Safety check blocks; staleness check does not.
4. **Auto-staging**: Updated shadow docs and the staleness manifest are
   automatically staged.

The pre-push hook has a similar structure but only warns (never blocks):

```bash
#!/bin/sh
# Osoji pre-push hook: Warn about stale shadow docs

cd "$REPO_ROOT"
ISSUES=$(osoji check . 2>&1)
ISSUE_COUNT=$(echo "$ISSUES" | grep -c "\[" || true)

if [ "$ISSUE_COUNT" -gt 0 ]; then
    echo "Found stale or missing shadow documentation:"
    echo "$ISSUES" | grep "\["
    echo "Consider running 'osoji shadow .' before pushing."
fi

# Don't block push, just warn
exit 0
```

---

## Troubleshooting

### Hook not running

If the hook does not seem to execute:

1. Verify it is installed:

   ```bash
   ls -la .git/hooks/pre-commit
   ```

2. Verify it is executable (Unix/macOS):

   ```bash
   chmod +x .git/hooks/pre-commit
   ```

3. Check that `osoji` is on your PATH:

   ```bash
   which osoji
   ```

### Hook runs but osoji not found

If you see "Warning: osoji not found, skipping checks":

- The hook searches PATH, `~/.local/bin/osoji`, and `/usr/local/bin/osoji`.
- If you installed via `pipx`, ensure `~/.local/bin` is on your PATH.
- If you installed in a virtual environment, the hook may not find it because
  the venv is not activated in the hook's shell context. Consider using
  `pipx` for a global install.

### detect-secrets not detecting expected secrets

- Verify it is installed: `pip show detect-secrets`
- Run `osoji safety patterns` and check the last line for
  "detect-secrets: installed"
- Some secret formats may not be recognized by the default `detect-secrets`
  plugins. The coverage depends on the `detect-secrets` version and
  configuration.

---

## Wrap-up

In this tutorial you have:

1. **Understood the risks** of committing personal paths and secrets.
2. **Run safety checks** manually on staged files and specific files.
3. **Viewed detection patterns** to understand what Osoji looks for.
4. **Created test violations** and seen them caught by both path and secret
   detection.
5. **Run the self-test** to verify Osoji's own codebase is clean.
6. **Installed git hooks** to automate safety checks on every commit.
7. **Experienced the hook blocking a commit** with violations.
8. **Fixed the violations** and committed successfully.

### Key takeaways

- `osoji safety check` catches personal paths (6 regex patterns) and secrets
  (via `detect-secrets`).
- `osoji hooks install` sets up automatic pre-commit checking.
- The pre-commit hook blocks commits with violations (exit code 1).
- `osoji safety patterns` shows exactly what is being detected.
- `osoji safety self-test` verifies the Osoji package itself is clean.
- Use `git commit --no-verify` only as a last resort to bypass the hook.

### Next steps

- **Getting Started with the CLI** (tutorial) -- If you have not yet explored
  the full Osoji command surface.
- **Running Your First Documentation Audit** (tutorial) -- Use Osoji to
  assess your documentation quality.
- **SECURITY.md** -- Review the project's security model and vulnerability
  reporting process.
