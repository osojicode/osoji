You are running a **dependency security scan** for the osoji project. This checks
all installed Python dependencies for known vulnerabilities using pip-audit.

## Arguments

$ARGUMENTS

Optional flags:
- `--fix` — automatically remediate findings (update deps, regenerate lock, create PR)
- `--json` — include raw JSON output from pip-audit

If no arguments are provided, run a standard scan and report findings.

## Phase 0 — Setup

1. Verify pip-audit is available:
   ```bash
   pip-audit --version
   ```
   If not installed: `pip install pip-audit`

2. Capture context:
   ```bash
   git rev-parse --short HEAD
   python --version
   ```

## Phase 1 — Scan

Run pip-audit against the current environment:

```bash
pip-audit
```

If `$ARGUMENTS` contains `--json`, also capture structured output:
```bash
pip-audit --format=json --output=/tmp/audit.json
```

## Phase 2 — Analyze

If vulnerabilities were found, assess each one:

1. **Direct or transitive?** Check if the package appears in `pyproject.toml`
   (direct) or only in `requirements.lock` (transitive).
2. **Fix available?** Does pip-audit report a fixed version?
3. **Reachable?** Does osoji actually import or use the vulnerable package's
   affected functionality? Check with:
   ```bash
   grep -r "<package>" src/osoji/
   ```
4. **Advisory details:** Note the advisory ID (CVE, PYSEC, etc.) and severity.

## Phase 3 — Report

**If no vulnerabilities found**, output a single line:
```
Security scan clean at <COMMIT_SHA> (<DATE>)
```
This keeps output minimal when used with `/loop`.

**If vulnerabilities found**, output a structured report:

```
## Security Scan — <DATE>

**Findings:** N vulnerabilities in M packages

| Package | Installed | Fixed | Advisory | Direct? | Action |
|---------|-----------|-------|----------|---------|--------|
| ...     | ...       | ...   | ...      | ...     | ...    |

### Recommended actions
1. ...
```

## Auto-fix (if --fix flag)

If `$ARGUMENTS` contains `--fix`:

1. For each finding with an available fix:
   - Update the version constraint in `pyproject.toml`
   - Or add an upper-bound exclusion if no safe upgrade exists
2. Regenerate the lock file:
   ```bash
   uv pip compile pyproject.toml --generate-hashes -o requirements.lock
   ```
3. Re-run pip-audit to confirm all findings are resolved.
4. Run tests:
   ```bash
   pytest -x -q -m "not prompt_regression and not live_smoke"
   ```
5. Create a PR:
   ```bash
   git checkout -b security/dep-update-<date>
   git add pyproject.toml requirements.lock
   git commit -m "fix: update dependencies to resolve security advisories"
   git push -u origin security/dep-update-<date>
   gh pr create --title "Security: resolve dependency advisories" --body "..."
   ```

Do NOT auto-merge. The project owner merges manually.
