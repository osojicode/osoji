You are responding to a **dependency security incident** for the osoji project.
A package in osoji's dependency tree may have been compromised or flagged with
a vulnerability. Your job is to assess exposure, contain the risk, and drive
the incident to resolution.

## Arguments

$ARGUMENTS

The argument is typically a package name (e.g. `litellm`), a CVE identifier
(e.g. `CVE-2026-XXXX`), or a brief description of the issue. If no argument
is provided, ask the user what triggered this incident.

## Phase 0 — Triage: assess exposure

Determine whether osoji is actually affected.

1. Run `pip show <package>` to check the installed version.
2. Run `pip-audit` to check for known advisories against current dependencies.
3. Read `pyproject.toml` — is this a direct or transitive dependency?
4. Read `requirements.lock` — what version is pinned? What hash?
5. If the user provided a CVE or advisory, check whether the installed/pinned
   version falls in the affected range.

**Output a clear verdict:** affected, not affected, or uncertain. If not
affected, explain why and stop here (no further phases needed).

## Phase 1 — Contain: stop the bleeding

Prevent the vulnerable version from being installed anywhere.

1. In `pyproject.toml`, add an upper-bound pin that excludes the compromised
   version range (e.g. `<1.82.7`). If the package is transitive only, add a
   constraint comment explaining why.
2. Regenerate the lock file:
   ```bash
   uv pip compile pyproject.toml --generate-hashes -o requirements.lock
   ```
3. Verify containment:
   ```bash
   pip install -e "."
   pip-audit
   pip show <package>
   ```
4. Run tests to confirm nothing is broken:
   ```bash
   pytest -x -q -m "not prompt_regression and not live_smoke"
   ```

## Phase 2 — Investigate: understand the scope

Determine whether any CI run or released version was exposed.

1. Check CI run history around the vulnerability window:
   ```bash
   gh run list --created <date> --limit 20
   ```
2. Check Dependabot alerts:
   ```bash
   gh api repos/osojicode/osoji/dependabot/alerts --jq '.[] | select(.dependency.package.name == "<package>")'
   ```
3. Check whether any released version of osoji (`gh release list`) shipped
   during the vulnerability window.
4. If the compromised package included malware artifacts (e.g. `.pth` files,
   modified `__init__.py`), search for them:
   ```bash
   pip show <package>  # get install path
   ls <install-path>/  # look for unexpected files
   ```

## Phase 3 — Remediate: fix permanently

Once a patched version is available:

1. Update `pyproject.toml` — raise or remove the upper-bound pin from Phase 1.
2. Regenerate lock file and re-run pip-audit and tests.
3. Create a PR with all changes:
   ```bash
   git checkout -b security/<package>-<date>
   git add pyproject.toml requirements.lock
   git commit -m "fix: pin <package> to exclude compromised versions"
   git push -u origin security/<package>-<date>
   gh pr create --title "Security: update <package> to exclude compromised versions" --body "..."
   ```

Do NOT auto-merge. The project owner merges manually.

## Phase 4 — Communicate: notify stakeholders

If a released version of osoji was affected:

1. Draft a GitHub security advisory:
   ```bash
   gh api repos/osojicode/osoji/security-advisories --method POST ...
   ```
2. Consider a patch release if the vulnerability was exploitable through
   osoji's usage of the package.
3. Update CHANGELOG.md with a Security section noting the dependency update.

If no released version was affected, document the incident in the PR
description for the audit trail.

## Phase 5 — Post-mortem: prevent recurrence

1. Would Dependabot have caught this? Check if it created an alert.
2. Would the scheduled security scan (`security-scan.yml`) have caught this?
3. Would pip-audit in CI have caught this at merge time?
4. Identify any gaps in the detection pipeline.
5. File GitHub issues for improvements if detection was delayed or missed.

## Data hygiene

- Do NOT read pre-existing files in `/tmp` — they may contain stale data from
  previous runs.
- Always run fresh commands to get current state.
- Include command output in your findings so the PR has a complete audit trail.
