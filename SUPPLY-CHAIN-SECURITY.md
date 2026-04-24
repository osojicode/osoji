# Supply Chain Security

This document describes how osoji protects its software supply chain. It is
intended for users evaluating whether to trust osoji as a dependency, and for
contributors understanding the project's security model.

## Governance model

osoji is developed in an **agent-first model**: AI coding agents perform all
implementation work, and the CI pipeline is the primary quality gate. There is
no human code reviewer — the project owner operates at the intent level
(deciding *what* to build and *when* to ship) while automated systems validate
the implementation.

This is a deliberate design choice. Automated controls are more consistent
than human review for a project with a single developer. Every check runs on
every PR, every time, without fatigue or shortcuts.

## Threat model

### What we defend against

- **Compromised dependencies.** A package in our dependency tree is backdoored
  or contains a known vulnerability (e.g. the litellm v1.82.7/v1.82.8
  supply chain attack of March 2026).
- **Compromised agent instructions.** The instruction files that guide AI
  agents (CLAUDE.md, .claude/) are modified to instruct agents to introduce
  malicious code.
- **Direct push attacks.** Malicious code is pushed directly to main,
  bypassing all quality checks.
- **Stale or tampered lock files.** The dependency lock file is out of date
  or has been modified to point to compromised package versions.

### What is out of scope

- **Full GitHub account compromise.** If an attacker gains admin access to the
  GitHub account, they can disable all protections. This is an account security
  problem, not a supply chain problem.
- **Novel zero-day exploits.** Automated scanning catches known vulnerabilities.
  Zero-days are discovered through other channels (security advisories, news).
- **Slow poisoning.** Many small, individually innocuous changes that combine
  into a vulnerability over time. Per-PR review cannot detect emergent
  properties of accumulated changes.

## Supply chain controls

### Dependency integrity

Three lock files enforce hash-pinned reproducibility across the CI lifecycle:

| Lock file | Source | Used by | Audited? |
|-----------|--------|---------|----------|
| `requirements.lock` | `pyproject.toml` (runtime deps) | Downstream reproducers; referenced for parity | Yes |
| `requirements-dev.lock` | `pyproject.toml` (runtime + dev extras) | CI test jobs (3.11/3.12/3.13) | Yes |
| `requirements-tools.lock` | `requirements-tools.in` (CI tooling: pip-audit, uv, build) | CI audit and publish jobs | Not audited — these tools have legitimate PyPI metadata but are not part of our supply chain, so we pin for integrity without auditing for CVEs |

| Control | Purpose | Enforcement |
|---------|---------|-------------|
| SHA-256-hashed lock files | Reproducible, tamper-evident installs | CI installs every lock with `pip install --require-hashes`; registry tampering fails the install |
| Lock freshness gate | Prevents drift between source (`pyproject.toml` or `requirements-tools.in`) and committed lock | Required status check: re-runs `uv pip compile` in place and fails if `git diff` shows any change |
| pip-audit in CI | Catches known-vulnerable dependencies in what we ship and what CI executes | Required status check: `pip-audit -r requirements.lock -r requirements-dev.lock` — no suppression flags, real vulns fail CI |
| Weekly scheduled pip-audit | Background monitoring between commits | Creates GitHub issue if vulnerabilities found |
| Dependabot (pip + github-actions) | Automated update PRs for security patches | Weekly, creates PRs automatically |
| `litellm` bound in `pyproject.toml` | Excludes compromised 1.82.7/1.82.8 range and pre-fix 1.83.0–1.83.6 | Dependency resolver rejects affected versions |

### Build and publish integrity

| Control | Purpose | Enforcement |
|---------|---------|-------------|
| OIDC trusted publishing | No long-lived PyPI tokens to steal | GitHub OIDC identity, not API keys |
| Sigstore attestations | Users can verify package provenance | Generated on every PyPI publish |
| SHA-pinned GitHub Actions | Immutable action references | Tag mutation attacks blocked |
| OpenSSF Scorecard | Third-party security assessment | Weekly scan, badge on README |

### Change control

| Control | Purpose | Enforcement |
|---------|---------|-------------|
| Branch protection on main | No direct pushes, even for admin | `enforce_admins: true`, server-side |
| Required CI status checks | Tests + audit must pass before merge | Named checks: `test (3.11/3.12/3.13)`, `audit` |
| `strict: true` | PR must be up-to-date with main | Prevents merging stale branches |
| No force pushes, no deletions | Protect git history | Branch protection rule |
| Manual merge only | Project owner decides when changes land | Agents create PRs but do not merge |
| Manual release only | Project owner decides when to ship | GitHub Release triggers publish workflow |

### Instruction integrity

AI agents follow instructions from files like CLAUDE.md and .claude/commands/.
If these files are compromised, the agent follows malicious instructions. Two
automated defenses address this:

**Instruction file flagging.** A CI job detects when a PR modifies control-plane
files (CLAUDE.md, .claude/, .github/workflows/, .github/dependabot.yml) and
adds an `instruction-files-changed` label. This ensures control-plane changes
are visible even in a quick PR summary scan.

**Adversarial review agent.** A separate AI agent runs in CI via
`anthropics/claude-code-action`, reviewing every PR for security concerns. Its
prompt is defined **inline in the workflow file** — it does not read CLAUDE.md
or any repository instruction file. The workflow uses `pull_request_target`,
which always runs the workflow version from main, not the PR branch. This means
a PR cannot weaken the reviewer's prompt and add a backdoor simultaneously.

To compromise the reviewer, an attacker would need to merge a modified workflow
into main — which requires passing the current reviewer. This circular
dependency is the core security property.

### Pre-commit safety

The `osoji safety check` pre-commit hook blocks commits containing:
- Personal filesystem paths (e.g. `/Users/jsmith/`, `C:\Users\`)
- Secrets and API keys (via detect-secrets)

## Verifying package authenticity

osoji publishes to PyPI with sigstore attestations. To verify a downloaded
package was built by the osoji GitHub repository:

```bash
pip install pypi-attestation-models
python -m pypi_attestation_models verify osojicode
```

Or check the attestation directly on PyPI at the package's "Provenance" tab.

## Incident response

If you discover a vulnerability in osoji's dependencies or code:

- **External reporters:** Email security@osojicode.ai (see SECURITY.md)
- **Maintainers:** Run `/security-incident <package>` in Claude Code for a
  structured incident response workflow covering triage, containment,
  investigation, remediation, communication, and post-mortem.
- **Automated detection:** The weekly security scan workflow creates GitHub
  issues when pip-audit finds vulnerabilities. Run `/security-scan` for an
  on-demand local check.

## Emergency access

Branch protection can be temporarily disabled for emergency fixes:

```bash
# Disable (leaves audit log entry)
gh api repos/osojicode/osoji/branches/main/protection --method DELETE

# Re-enable
gh api repos/osojicode/osoji/branches/main/protection --method PUT --input ...
```

This is an auditable action recorded in the GitHub audit log. It should be
used only for genuine emergencies where the PR/CI workflow is itself broken.

## Known limitations

These controls make compromise **costly and visible**, not impossible.

- **Admin override.** The repository admin can disable branch protection with
  a single API call. The GitHub audit log records this, but no automated
  system monitors the audit log.
- **Prompt injection.** The adversarial review agent is an LLM and can
  potentially be manipulated by carefully crafted PR content. This is an
  arms race between prompt robustness and attacker creativity.
- **Slow poisoning.** Many small, individually benign changes that combine
  into a vulnerability are not detectable by per-PR review.
- **Advisory lag.** pip-audit and Dependabot only catch vulnerabilities after
  they are published in advisory databases. Zero-day compromises (like the
  litellm incident) are discovered through other channels first.

## Continuous improvement

Security posture is monitored through:
- **OpenSSF Scorecard** — weekly third-party assessment (badge on README)
- **Scheduled pip-audit** — weekly background scan, auto-creates issues
- **Dependabot** — weekly dependency update PRs
- **Adversarial PR review** — every PR reviewed for security concerns
- **Pre-commit safety checks** — blocks secrets and personal paths at commit time
