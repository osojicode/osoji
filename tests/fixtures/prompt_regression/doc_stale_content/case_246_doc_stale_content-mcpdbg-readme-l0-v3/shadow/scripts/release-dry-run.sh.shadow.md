# scripts\release-dry-run.sh
@source-hash: 04e27eb9086dc91c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:14Z

## Release Dry-Run Script (`scripts/release-dry-run.sh`)

Pre-release validation script that runs a series of checks to confirm the release pipeline will succeed before tagging. Intended to be run via `npm run release:dry-run`.

### Invocation
```bash
npm run release:dry-run
# or directly:
bash scripts/release-dry-run.sh
```
Exit code: `0` = all checks passed; `1` = one or more checks failed.

---

### Output Helpers (L12–14)
- `pass()` — prints green ✓ message
- `fail()` — prints red ✗ message and sets `FAIL=1` (global failure flag, L10)
- `warn()` — prints yellow ! message (non-blocking)

---

### Check Sequence

#### 1. Version Consistency (L21–51)
Reads `version` from `package.json` of all 11 packages using `node -e require(...)`:
- Root, shared, adapter-mock, adapter-python, adapter-ruby, adapter-go, adapter-java, adapter-javascript, adapter-rust, adapter-dotnet, mcp-debugger (L23–33)
- All must equal `ROOT_VER`; any mismatch → `fail` (L47–51)

#### 2. CHANGELOG Validation (L53–66)
- Verifies `CHANGELOG.md` contains `## [<ROOT_VER>] - YYYY-MM-DD` entry (L56)
- Verifies top 20 lines contain `## [Unreleased]` section (L62)

#### 3. Build (L68–75)
- Runs `npm run build`, suppressing output (L71)

#### 4. Unit Tests (L77–84)
- Runs `npm run test:unit`, suppressing output (L80)

#### 5. npm Pack Dry-Run + Provenance Readiness (L86–105)
- Iterates over 5 published packages: `shared`, `adapter-mock`, `adapter-python`, `adapter-ruby`, `mcp-debugger` (L89)
- For each: runs `npm pack --dry-run -w <pkg_name>` (L92)
- Checks `repository.url` in each package's `package.json` contains `github.com/debugmcp/mcp-debugger` (L100); required for `--provenance` flag on publish (E422 error if missing)

#### 6. GitHub Secrets + Token Validation (L107–165)
- Requires `gh` CLI; if absent → warn and skip (L111, L156–158)
- Checks presence of `NPM_TOKEN`, `DOCKER_USERNAME`, `DOCKER_PASSWORD`, `PYPI_TOKEN` in `gh secret list` (L114–120)
- Triggers `validate-secrets.yml` workflow on GitHub Actions (L125); waits for completion via `gh run watch` (L131)
- Reports per-job pass/fail/warn from workflow results (L136–145)
- Checks if any of the 5 published packages already exist at `ROOT_VER` on npm registry (L161–165); warns (non-blocking) if already published

#### 7. `release.yml` Sanity Checks (L167–187)
- Confirms `.github/workflows/release.yml` references `setup-java` (JDK 21 for JDI bridge) (L170)
- Confirms it references `setup-go` (L176)
- Confirms the changelog extraction step strips the `v` prefix from git tag refs (`RELEASE_REF#refs/tags/` → `tags/v}`) (L182–187)

#### 8. Git State (L189–203)
- Warns (non-blocking) if working tree has uncommitted changes (L192–196)
- Warns (non-blocking) if not on `main` branch (L198–203)

---

### Summary (L205–217)
- If `FAIL=0`: prints "All checks passed" and the exact `git tag` / `git push` commands to release
- If `FAIL≠0`: prints "Some checks failed"
- Script exits with `$FAIL` (0 or 1)

---

### Published Package Scope
The 5 npm-published packages are: `@debugmcp/shared`, `@debugmcp/adapter-mock`, `@debugmcp/adapter-python`, `@debugmcp/adapter-ruby`, `@debugmcp/mcp-debugger`.
The adapter packages for Go, Java, JavaScript, Rust, and .NET are version-checked but NOT pack-tested or published via npm.

### Key External Dependencies
- `node` (inline JSON parsing)
- `npm` (build, test, pack)
- `gh` CLI (optional — GitHub secrets + workflow trigger)
- `git` (working tree state, branch detection)
