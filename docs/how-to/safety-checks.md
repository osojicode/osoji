# How to Set Up and Use Safety Checks for Personal Paths and Secrets

## How to run a one-off safety check

### Check staged files

To check all files currently staged in git for personal paths and secrets:

```bash
osoji safety check
```

This calls `check_staged_files()` internally, which uses `git diff --cached --name-only --diff-filter=ACM` to find added, copied, or modified staged files. The command exits with code 0 if no issues are found, and code 1 if any personal paths or secrets are detected.

**Clean result output:**

```
Safety check passed - no issues found.
```

**Failed result output:**

```
Safety check FAILED

## Personal Paths Found (2)

**src/config.py**
  Line 42: `C:\Users\jsmith\projects\myapp\`
    Pattern: windows_user
  Line 58: `/home/jsmith/data/`
    Pattern: unix_home

---

Replace personal paths with generic alternatives:
  - /path/to/project
  - ~/workspace/project
  - ./relative/path

To bypass in emergencies: git commit --no-verify

---
Total: 2 issue(s) in 1 file(s)
```

### Check specific files

To check one or more specific files without staging them:

```bash
osoji safety check src/config.py src/utils.py
```

Each file path must exist. The files are resolved to absolute paths and checked through the same pipeline as staged files.

## How to run a self-test

The self-test verifies that the Osoji package itself does not contain accidental personal paths:

```bash
osoji safety self-test
```

This scans all Python files in the installed `osoji` package (excluding `paths.py` itself, which has its own specialized self-test that filters out matches in comments, docstrings, and documentation examples). The command exits with code 0 if clean, code 1 if personal paths are found.

Run this:
- After modifying safety detection patterns
- In CI to verify the package remains clean
- After contributing code that includes file path examples

**Clean output:**

```
Self-test passed - no personal paths found in osoji package
```

## How to view active patterns

To see all regex patterns currently used for personal path detection:

```bash
osoji safety patterns
```

**Output:**

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

The patterns are defined as compiled regex objects in `src/osoji/safety/paths.py` in the `PATTERNS` dictionary. Each pattern has a corresponding human-readable description in `PATTERN_DESCRIPTIONS`.

The patterns intentionally exclude common generic/CI usernames (`test`, `user`, `example`, `runner`, `ubuntu`) to avoid flagging paths in CI environments or documentation examples.

## How to install git hooks

### Install hooks

To install Osoji's pre-commit and pre-push hooks:

```bash
osoji hooks install
```

This installs two hooks by default:

- **pre-commit**: Runs `osoji safety check` (blocks commit on failure) then `osoji check .` (marks stale shadow docs, stages updates)
- **pre-push**: Runs `osoji check .` and warns about stale shadow docs (does not block push)

**Output:**

```
pre-commit: installed
pre-push: installed
```

To overwrite existing hooks (including non-Osoji hooks):

```bash
osoji hooks install --force
```

If existing Osoji hooks are already installed, the command reports them without reinstalling unless `--force` is used.

### Verify hooks are installed

Check for the hook files in your git hooks directory:

```bash
ls .git/hooks/pre-commit .git/hooks/pre-push
```

The hooks are shell scripts containing an `osoji` marker comment. They locate the `osoji` binary by checking `PATH` first, then common installation locations (`~/.local/bin/osoji`, `/usr/local/bin/osoji`).

### Uninstall hooks

To remove all Osoji-installed hooks:

```bash
osoji hooks uninstall
```

This only removes hooks that contain the `osoji` marker -- non-Osoji hooks are left untouched. The command checks each hook file for the word "osoji" before removing it.

**Output:**

```
pre-commit: removed
pre-push: removed
```

## How to integrate with CI/CD

### Basic CI integration

Add a safety check step to your CI pipeline. The command exits with code 1 on failure, which causes CI to fail the build:

```yaml
# GitHub Actions example
- name: Safety check
  run: |
    pip install osojicode
    osoji safety check $(git diff --name-only HEAD~1)
```

### Check specific files changed in a PR

```bash
# Check only files changed in this branch
osoji safety check $(git diff --name-only origin/main...HEAD)
```

### Exit codes

| Exit code | Meaning                                |
| --------- | -------------------------------------- |
| 0         | No issues found                        |
| 1         | Personal paths or secrets detected     |

## How to configure file filtering

The safety module checks files based on their extension and location, using rules defined in `src/osoji/safety/filters.py`.

### Which files are checked

Files with these extensions are checked:

- **Code**: `.py`, `.pyi`, `.js`, `.ts`, `.mjs`, `.jsx`, `.tsx`
- **Config**: `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`
- **Docs**: `.md`, `.txt`, `.rst`
- **Shell**: `.sh`, `.bash`, `.zsh`
- **Environment**: `.env` (both as extension and as filename prefix like `.env.local`)
- **Database**: `.sql`
- **Markup**: `.xml`, `.html`, `.htm`
- **No extension**: Files without an extension are checked (they may be scripts like `Makefile`)

### Which files are skipped

**Binary files** -- images, PDFs, archives, executables, fonts, compiled files, and database files are skipped entirely (full list in `BINARY_EXTENSIONS`).

**Skipped directories** -- files under these directories are excluded: `.git`, `__pycache__`, `node_modules`, `venv`, `.venv`, `build`, `dist`, `.osoji`, and other common generated/cache directories (full list in `SKIP_DIRECTORIES`).

**Safety module self-exclusions** -- the `paths.py` source file itself and test files in the safety directory are excluded to avoid circular detection (these files intentionally contain example personal paths).

### Check if a specific file would be included

Use the `should_check_file` function programmatically:

```python
from pathlib import Path
from osoji.safety.filters import should_check_file

print(should_check_file(Path("src/config.py")))     # True
print(should_check_file(Path("image.png")))           # False
print(should_check_file(Path("node_modules/pkg.js"))) # False
```

## How to use detect-secrets integration (optional)

### Installing the dependency

The `detect-secrets` library provides additional secret detection patterns beyond personal paths. Install it as an optional dependency:

```bash
pip install 'osojicode[safety]'
```

### What additional patterns this enables

When `detect-secrets` is installed, the safety checker scans for:

- AWS access keys and secret keys
- Private keys (RSA, DSA, ECDSA, etc.)
- High-entropy strings that look like tokens
- Other secret patterns supported by the `detect-secrets` plugin ecosystem

Without `detect-secrets`, the safety checker still runs all personal path detection patterns. Secret detection is simply skipped with a debug-level log message.

### Checking installation status

```bash
osoji safety patterns
```

The output includes a line at the bottom indicating whether `detect-secrets` is installed:

```
detect-secrets: installed (secrets will be checked)
```

or:

```
detect-secrets: not installed
  Install with: pip install 'osoji[safety]'
```

### How detection works

The secret detection in `src/osoji/safety/secrets.py` wraps `detect-secrets` with error handling:

```python
from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings

secrets = SecretsCollection()
with default_settings():
    secrets.scan_file(str(file_path))
```

If `detect-secrets` encounters an error (binary file, permission issue, internal error), the error is logged at debug level and the file is skipped. The safety check continues with other files.

## How to use safety checks programmatically

The safety module is designed for potential future extraction as a standalone package. Its programmatic API is clean and self-contained.

### Batch checking

```python
from pathlib import Path
from osoji.safety import check_files, CheckResult

result: CheckResult = check_files([
    Path("src/config.py"),
    Path("src/utils.py"),
    Path("README.md"),
])

if not result.passed:
    print(f"Found {result.finding_count} issue(s)")
    for finding in result.path_findings:
        print(f"  {finding.file}:{finding.line_number}: {finding.match}")
```

### Git-staged checking

```python
from osoji.safety import check_staged_files

result = check_staged_files()
print(result.summary())
# "Safety check passed - 5 file(s) checked"
# or "Safety check FAILED - 3 issue(s) in 2 file(s)"
```

### Formatting results

```python
from osoji.safety import check_files, format_check_result

result = check_files(file_list)
report = format_check_result(result, verbose=True)
print(report)
```

The `verbose=True` option includes file counts and a note about `detect-secrets` availability.

### Data models

**`CheckResult`** -- combined result for one or more files:

| Field             | Type                  | Purpose                              |
| ----------------- | --------------------- | ------------------------------------ |
| `path_findings`   | `list[PathFinding]`   | Personal path matches                |
| `secret_findings` | `list[SecretFinding]` | Potential secret detections          |
| `files_checked`   | `int`                 | Number of files examined             |
| `files_skipped`   | `int`                 | Number of files excluded by filters  |
| `errors`          | `list[str]`           | Error messages (missing files, etc.) |
| `passed`          | `bool` (property)     | True if no findings of any kind      |
| `finding_count`   | `int` (property)      | Total path + secret findings         |

`CheckResult` supports merging via the `merge` method, which combines findings, counts, and errors from two results into a new `CheckResult`.

**`PathFinding`** -- a detected personal path:

| Field          | Type   | Purpose                                     |
| -------------- | ------ | ------------------------------------------- |
| `file`         | `Path` | File containing the match                    |
| `line_number`  | `int`  | Line number (1-indexed)                      |
| `line_content` | `str`  | The full line text (stripped)                 |
| `pattern_name` | `str`  | Which pattern matched (e.g., `"unix_home"`)  |
| `match`        | `str`  | The matched substring                        |

**`SecretFinding`** -- a detected potential secret:

| Field         | Type   | Purpose                                  |
| ------------- | ------ | ---------------------------------------- |
| `file`        | `Path` | File containing the detection            |
| `line_number` | `int`  | Line number (1-indexed)                  |
| `secret_type` | `str`  | Type of secret (e.g., `"AWS Access Key"`)|
