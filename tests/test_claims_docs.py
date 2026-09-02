"""Tests for mechanical claim extraction from markdown (Tier A)."""

import textwrap

from osoji.claims_docs import DocClaim, extract_doc_claims, is_placeholder


def _claims(md: str) -> list[DocClaim]:
    return extract_doc_claims("docs/guide.md", textwrap.dedent(md))


def test_extracts_npm_and_pnpm_script_claims_with_ecosystem():
    claims = _claims("""\
        Build with `npm run build:packages`, then run `pnpm run test:ui`.

        ```bash
        pnpm test:e2e
        yarn lint
        ```
        """)
    scripts = [(c.name, c.ecosystem, c.in_fence, c.line) for c in claims if c.kind == "script_exists"]
    assert ("build:packages", "npm", False, 1) in scripts
    assert ("test:ui", "npm", False, 1) in scripts
    assert ("test:e2e", "npm", True, 4) in scripts
    assert ("lint", "npm", True, 5) in scripts


def test_package_manager_builtins_are_not_script_claims():
    claims = _claims("Run `npm install` then `pnpm install --frozen-lockfile` and `npm ci`.\n")
    assert [c for c in claims if c.kind == "script_exists"] == []


def test_extracts_make_targets():
    claims = _claims("Type `make docker-e2e` to run the suite.\n")
    assert [(c.name, c.ecosystem) for c in claims if c.kind == "script_exists"] == [("docker-e2e", "make")]


def test_extracts_repo_relative_path_claims_from_backticks():
    claims = _claims("""\
        See `src/server/tool-schemas.ts` and the `docs/architecture/` folder.
        The entry point is `packages/mcp-debugger/dist/index.js`.
        """)
    paths = sorted(c.name for c in claims if c.kind == "path_exists")
    assert paths == ["docs/architecture", "packages/mcp-debugger/dist/index.js", "src/server/tool-schemas.ts"]


def test_rejects_placeholders_urls_absolute_and_bare_words():
    claims = _claims("""\
        Use `path/to/your/file.ts` or `<project>/src/x.ts` or `src/**/*.ts` or `${ROOT}/a.ts`.
        Open `https://example.com/docs/x.md` or `/usr/local/bin/node` or `C:\\Users\\me\\a.ts`.
        Call `initialize` and pass `--stdio`.
        """)
    assert claims == []
    assert is_placeholder("path/to/file") is True
    assert is_placeholder("src/a.ts") is False


def test_claim_carries_source_span_and_text():
    claims = _claims("Edit `packages/shared/README.md` first.\n")
    (claim,) = claims
    assert claim.doc_path == "docs/guide.md"
    assert claim.line == 1
    assert claim.text == "packages/shared/README.md"
    assert claim.in_fence is False
