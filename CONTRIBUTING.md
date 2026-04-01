# Contributing to Osoji

Contributions are welcome — from humans and AI coding agents alike.

The best way to contribute: run `osoji audit` on your own projects, use the
bundled skill files (`osoji-sweep`, `osoji-triage`) to triage findings, and let
the skill workflow file issues for false positives and missed detections.

```bash
osoji skills show osoji-sweep      # Full end-to-end audit workflow
osoji skills show osoji-triage    # Read-only triage and review
```

False-positive reports and missed-detection issues filed through the skill
workflow are the highest-impact contributions. They directly improve the
pipeline for everyone.

## Development setup

```bash
git clone https://github.com/osojicode/osoji.git
cd osoji
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

See [CLAUDE.md](CLAUDE.md) for additional architecture notes and conventions.

## Running tests

```bash
pytest                                                # Deterministic tests (no API calls)
pytest -m prompt_regression                           # Prompt regression suite (requires ANTHROPIC_API_KEY)
pytest -m prompt_regression --establish-baseline       # Re-establish baselines after prompt changes
```

## Code style

There is no enforced formatter or linter at this time. Follow the conventions
you see in existing code: type hints throughout, imperative-mood docstrings,
async where needed (LLM calls), sync otherwise. Python 3.11+.

## The prompt module boundary

LLM prompts in the analysis pipeline are closed-source. This is intentional —
they are core IP. The following kinds of contributions are all welcome:

- Structural pipeline work (new phases, orchestration improvements)
- New finding types and detection logic
- Bug fixes
- AST plugins for additional languages (see `src/osoji/plugins/`)
- Documentation
- Test coverage

## Prompt contributions

Osoji's LLM prompts are finely tuned and interdependent. The repo includes a
statistical prompt regression suite that runs each prompt behavior multiple
times against the real Anthropic API and uses binomial hypothesis testing to
detect regressions. The suite automatically computes the sample size needed
for 99% statistical power, so stochastic LLM behavior doesn't cause false
test failures.

If your PR modifies prompts:

1. Run `pytest -m prompt_regression` and confirm all cases pass.
2. If you're changing behavior that an existing case covers, re-establish
   its baseline with `pytest -m prompt_regression --establish-baseline`.
3. For new prompt behaviors, consider adding a regression case — see
   `tests/fixtures/prompt_regression/` for the fixture structure.

If you've found a false-positive pattern but don't want to dig into prompts,
the fastest path is to run the `osoji-sweep` skill on your project — it will
automatically file a structured GitHub issue with the evidence osoji needs
to improve.

Note: prompt regression tests hit the real Anthropic API and are skipped by
default in `pytest` and CI.

## Submitting pull requests

All changes to `main` go through pull requests — there are no direct pushes.
Branch protection requires CI status checks to pass before merging. There is
no human code reviewer; the CI pipeline is the merge gate.

1. Fork the repo (or create a feature branch if you have push access).
2. Make your changes. Keep PRs focused — one logical change per PR.
3. Add tests for new functionality.
4. Run `pytest` and make sure tests pass.
5. If prompts were changed, include passing `pytest -m prompt_regression` results.
6. If dependencies were changed, regenerate the lock file:
   `uv pip compile pyproject.toml --generate-hashes -o requirements.lock`
7. Submit a pull request. CI will run automatically.

## Reporting bugs

Please use the [bug report template](https://github.com/osojicode/osoji/issues/new?template=bug_report.yml).
Include your `osoji --version` output, Python version, and the LLM provider/model
you were using.

## Security

To report security vulnerabilities, see [SECURITY.md](SECURITY.md).

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating, you agree to uphold its terms.
