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


def test_prose_command_words_outside_backticks_are_not_script_claims():
    # Regression for fix round 1, finding 1: "make sure" and "pnpm -r" are
    # ordinary English, not commands, when they appear un-backticked in prose.
    claims = _claims(
        "Always make sure the cache is warm, then pnpm -r build.\n"
    )
    assert claims == []


def test_backticked_prose_command_is_still_extracted():
    # Companion to the above: a *backticked* command in prose is still a
    # claim -- only raw, un-backticked prose is excluded.
    claims = _claims("Then run `npm run build`.\n")
    scripts = [(c.name, c.ecosystem) for c in claims if c.kind == "script_exists"]
    assert scripts == [("build", "npm")]


def test_strips_line_and_anchor_suffixes_from_path_claim_name():
    # Regression for fix round 1, finding 2: a `:line` or `#anchor` suffix
    # is part of how the doc points at the file, not part of the path
    # itself -- `name` should match what a path registry holds, while
    # `text` keeps the literal token as written.
    claims = _claims("See `src/a.ts:42` and `docs/guide.md#usage`.\n")
    by_name = {c.name: c.text for c in claims if c.kind == "path_exists"}
    assert by_name == {
        "src/a.ts": "src/a.ts:42",
        "docs/guide.md": "docs/guide.md#usage",
    }


def test_strips_line_range_and_trailing_slash_before_anchor():
    claims = _claims(
        "See `src/a.ts:10-20` and `docs/architecture/#overview`.\n"
    )
    names = sorted(c.name for c in claims if c.kind == "path_exists")
    assert names == ["docs/architecture", "src/a.ts"]


def test_scoped_package_name_is_not_a_path_claim():
    # A leading `@` marks a package scope/handle in every ecosystem (npm,
    # some Python/Go tooling) -- never a relative repo path. Same principle
    # as the existing `~` exclusion.
    claims = _claims(
        "The image vendors CodeLLDB under `@debugmcp/codelldb-common`, "
        "resolved via `CODELLDB_PATH`.\n"
    )
    assert [c for c in claims if c.kind == "path_exists"] == []


def test_package_manager_flag_after_pm_name_is_not_a_script_claim():
    # `pnpm --filter <pkg> build` -- `--filter` is a pnpm CLI flag, not a
    # script name. Only npm requires `run`; pnpm/yarn allow a bare script
    # name directly after the package manager, but a `-`-prefixed token is
    # never a script name in any package manager.
    claims = _claims("Run `pnpm --filter @debugmcp/mcp-debugger build`.\n")
    assert [c for c in claims if c.kind == "script_exists"] == []


def test_extracts_path_claim_from_markdown_link_target():
    # Real doc line (mcp-debugger docs/architecture/README.md:278): a footer
    # pointer written as a markdown link, not a backtick span.
    claims = _claims(
        "For the refactoring history, see "
        "[refactoring-summary.md](./refactoring-summary.md).\n"
    )
    names = [(c.name, c.kind) for c in claims if c.kind == "path_exists"]
    assert ("refactoring-summary.md", "path_exists") in names


def test_markdown_link_to_url_or_anchor_is_not_a_path_claim():
    claims = _claims(
        "See the [project homepage](https://example.com/docs) or "
        "[jump to usage](#usage).\n"
    )
    assert [c for c in claims if c.kind == "path_exists"] == []


def test_extracts_bare_path_argument_from_fenced_shell_line():
    # Real doc line (mcp-debugger CONTRIBUTING.md:189): a fenced ```bash```
    # block naming a test file with no backticks around it.
    claims = _claims("""\
        ```bash
        npx vitest run tests/unit/session/session-manager.test.ts
        ```
        """)
    names = [(c.name, c.kind, c.in_fence) for c in claims if c.kind == "path_exists"]
    assert ("tests/unit/session/session-manager.test.ts", "path_exists", True) in names


def test_fenced_shell_flag_or_assignment_token_is_not_a_path_claim():
    # A `VAR=value` assignment or `--flag=value` token that happens to
    # contain a "/" is not a path argument -- same principle as excluding
    # `-`-prefixed flags from script names.
    claims = _claims("""\
        ```bash
        MCP_WORKSPACE_ROOT=/workspace/project run.sh
        ```
        """)
    assert [c for c in claims if c.kind == "path_exists"] == []


def test_same_name_in_two_ecosystems_on_one_line_yields_two_claims():
    # Fix round 4, finding 4: the dedup key omitted the ecosystem, so `make
    # test` and `npm test` on one line collapsed into a single claim and the
    # other was never verified -- a silent coverage hole, not a visible error.
    claims = _claims("Run `make test` or `npm test`.\n")
    assert sorted((c.name, c.ecosystem) for c in claims if c.kind == "script_exists") == [
        ("test", "make"),
        ("test", "npm"),
    ]


def test_bare_directory_name_with_only_a_trailing_slash_is_not_a_path_claim():
    # Fix round 4: `_looks_like_repo_path` required a "/" but tested the raw
    # token, while `_norm_path` strips a trailing slash -- so ASCII-tree
    # entries like `shadow/` became bare-word path claims, exactly the shape
    # the module's own comment says is too ambiguous to check.
    claims = _claims("""\
        The layout is:

        - `shadow/` -- generated docs
        - `facts/` -- extracted facts
        """)
    assert [c for c in claims if c.kind == "path_exists"] == []


def test_directory_claim_with_a_real_separator_survives_the_trailing_slash_rule():
    claims = _claims("See the `docs/architecture/` folder.\n")
    assert [c.name for c in claims if c.kind == "path_exists"] == ["docs/architecture"]


# --- rulings wave: the creation-instruction guard ----------------------------


def test_creation_instruction_marks_the_claim_creation_modality():
    # An instruction to create the artifact does not assert that it exists;
    # a how-to that says "Create `x` with:" is right precisely while `x` is
    # absent, so verifying it against the checkout inverts its meaning.
    claims = _claims("Create `src/handlers/new_tool.ts` with:\n")
    (claim,) = [c for c in claims if c.kind == "path_exists"]
    assert claim.name == "src/handlers/new_tool.ts"
    assert claim.modality == "creation"


def test_a_pointer_to_an_existing_artifact_keeps_exact_modality():
    claims = _claims("See `src/handlers/tool.ts`\n")
    (claim,) = [c for c in claims if c.kind == "path_exists"]
    assert claim.modality == "exact"


def test_creation_verbs_are_matched_as_whole_words_case_insensitively():
    for line in ("Add `docs/new-page.md` to the index.\n",
                 "Then SAVE `config/local.json` alongside it.\n",
                 "Run mkdir and put `assets/logo/icon.svg` there.\n"):
        claims = [c for c in _claims(line) if c.kind == "path_exists"]
        assert claims and all(c.modality == "creation" for c in claims), line
    # "created"/"describes" are not the imperative: past tense and prose
    # describe a state, they do not instruct the reader to make something.
    claims = [c for c in _claims("The generator created `dist/out.js` already.\n")
              if c.kind == "path_exists"]
    assert [c.modality for c in claims] == ["exact"]


# --- rulings wave: bare package-manager words --------------------------------


def test_bare_pnpm_or_yarn_word_is_marked_not_explicitly_run():
    # `pnpm vitest` may run a node_modules/.bin binary rather than a declared
    # script -- the two are indistinguishable from the doc line alone.
    claims = _claims("Run `pnpm vitest` or `yarn tsc`.\n")
    assert [(c.name, c.explicit_run) for c in claims if c.kind == "script_exists"] == [
        ("vitest", False), ("tsc", False),
    ]


def test_explicit_run_and_npm_aliases_stay_decidable():
    claims = _claims("Run `pnpm run vitest`, `yarn run lint`, `npm run build` or `npm test`.\n")
    assert all(c.explicit_run for c in claims if c.kind == "script_exists")
    assert sorted(c.name for c in claims if c.kind == "script_exists") == [
        "build", "lint", "test", "vitest",
    ]


def test_make_target_is_explicitly_run():
    claims = _claims("Type `make docker-e2e`.\n")
    assert [(c.name, c.explicit_run) for c in claims if c.kind == "script_exists"] == [
        ("docker-e2e", True),
    ]


def test_npm_script_aliases_stay_decidable_under_every_package_manager():
    # `test`/`start` are `run` aliases in pnpm and yarn exactly as in npm --
    # they cannot resolve to a node_modules/.bin binary, so they stay
    # decidable whichever package manager the doc names.
    claims = _claims("Run `pnpm test` or `yarn start`.\n")
    assert [(c.name, c.explicit_run) for c in claims if c.kind == "script_exists"] == [
        ("test", True), ("start", True),
    ]
