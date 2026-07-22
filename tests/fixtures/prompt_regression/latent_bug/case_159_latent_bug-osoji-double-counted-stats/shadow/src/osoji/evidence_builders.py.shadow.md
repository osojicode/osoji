# src\osoji\evidence_builders.py
@source-hash: 2f16116e5f1144b9
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:15Z

## Purpose
Implements five concrete `EvidenceBuilder` subclasses for the mechanized Claim Builder (V1-4/V1-5). Each builder gathers a specific category of evidence for a `Finding` without raising exceptions — returning `[]` on failure. All builders are registered into `BUILDERS` at module load time.

## Architecture

### BuildContext (L60-148)
Shared, lazily-populated context injected into every builder call. Stateful cache for file reads, scan corpus, FactsDB, and symbols. Key methods:
- `facts()` (L76-81): Lazy-loads `FactsDB(config)`.
- `symbols()` (L83-88): Lazy-loads `load_all_symbols(config)`.
- `read_lines(rel_path)` (L90-102): Cached UTF-8 line read; `None` on `OSError`.
- `scan_files()` (L104-141): Builds the text-scan corpus from `list_repo_files()`, capped at `_MAX_SCAN_FILES=5000`. Records `_scan_truncated=True` if cap hit. POSIX-normalized root-relative paths.
- `scan_truncated()` (L143-147): Whether the last corpus build was capped.

### Constants (L48-57)
- `_MAX_SCAN_FILES = 5000` — corpus hard cap.
- `_MAX_HITS_PER_NEEDLE = 20` — per-symbol hit budget.
- `_MAX_HITS_PER_FILE = 3` — per-file diversity cap (named/priority files bypass).
- `_MAX_SCAN_ENTRIES_PER_CLAIM = 40` — total rendered entries cap.
- `_MAX_NEEDLES = 5` — needle list length cap.
- `_CONTEXT_LINES = 2` — surrounding context lines per hit.
- `_MAX_CONTEXT_LINE_CHARS = 200` — line truncation for context.
- `_REGION_PAD = 10` — lines of padding around flagged region.
- `_ENCLOSING_HEAD_LINES = 15` — head lines from enclosing symbol.
- `_SHADOW_EXCERPT_CHARS = 2000` — shadow doc excerpt length.

### Private Helpers (L152-431)

**`_SYMBOL_FILLER` (L152-156)**: Stop-word set for symbol extraction.

**`_extract_all_symbols_from_debris(description)` (L159-194)**: Extracts plausible symbol names from finding description text via three strategies: (1) backtick-quoted names, (2) PascalCase compounds (ReDoS-safe linear approach), (3) fallback bare-word.

**`_lookup_type_definitions(config, type_names, symbols_by_file)` (L197-227)**: Looks up class/type definitions in symbols DB; returns `{"type_name", "file", "source"}` dicts with numbered snippets (capped at 50 lines).

**`_infer_variable_type(config, source_path, line_number, description)` (L230-266)**: Extracts type names from variable annotations (`var: TypeName`) near the finding line, searching up to 40 lines backward.

**`_claim_text(finding)` (L269-270)**: Concatenates `contract_claim` and `observed_behavior`.

**`_scanner_meta(finding)` (L273-284)**: Returns the `payload` of the first `scanner_metadata` Evidence on the finding, or `{}`.

**`_match_in_quotes(line, pos)` (L287-308)**: Single-line state machine to detect if column `pos` is inside a quoted span (`'`, `"`, backtick). Used to flag `in_string_literal` on text scan hits.

**`_backticked_names(text)` (L311-338)**: Extracts backtick-delimited identifiers including dotted names and `name()` call forms. Dotted names contribute both qualified and bare-segment forms (>2 chars).

**`_scan_needles(finding)` (L341-364)**: Returns `(symbol_needles, literal_needles)`. Priority: detector-supplied `scan_needles` → `finding.symbol` → backticked names → prose fallback. Literals only included for `gap_type == "contract"`.

**`_quoted_literals(text)` (L367-376)**: Extracts single/double-quoted strings (2-80 chars) from claim prose; capped at `_MAX_NEEDLES`.

**`_named_paths(finding, ctx)` (L379-394)**: Extracts path-like tokens from claim text that exist in the corpus (contain `/` or `\`). These are swept first before the hit cap fills.

**`_find_symbol_entry(symbols_by_file, rel_path, name)` (L397-403)**: Looks up a named symbol with `line_start` in the symbols DB for a specific file.

**`_enclosing_symbol(symbols_by_file, rel_path, line)` (L406-419)**: Finds the smallest symbols-DB span containing `line`. Returns `{name, kind, line_start, line_end}`.

**`_numbered(lines, start, end)` (L422-430)**: Produces 1-based numbered snippet with line truncation at `_MAX_CONTEXT_LINE_CHARS * 2`.

**`_read_text(path)` (L735-741)**: Best-effort UTF-8 file read; empty string on `OSError`.

**`_scope_for(sources)` (L744-761)**: Determines shadow scope from a list of source paths: single source → `("file", path)`; same parent → `("directory", parent)`; multiple dirs or none → `("root", None)`.

### Builders

**`CrossFileReferenceBuilder` (L436-628)**, `kind = "cross_file_reference"`:
- FactsDB graph refs: tries detector-supplied needles → `finding.symbol` → prose extraction; picks the symbol that yields the most refs.
- Text scan: sweeps corpus in priority order (detector priority_paths → claim-named files → flagged file → rest sorted by source-extension rank then proximity). Applies `_MAX_HITS_PER_NEEDLE`, `_MAX_HITS_PER_FILE` (bypassed for named files), `_MAX_SCAN_ENTRIES_PER_CLAIM` caps while counting honest totals. Sets `in_string_literal` flag via `_match_in_quotes`.
- Export surface: checks if primary symbol is in `facts.exported_names(source)`.
- `scan_scope` includes `files_scanned`, `needles`, `needle_totals`, `same_file_swept`, and optionally `truncated`.
- Returns `[]` only if no graph, no corpus, and no export surface.
- `_shadow_excerpts(ctx, references)` (L621-628): Loads shadow docs for the first 3 referenced files.

**`SurroundingCodeBuilder` (L631-681)**, `kind = "surrounding_code"`:
- Anchors on symbols DB entry or nearest word-boundary match to `finding.symbol`; falls back to `finding.line_start/line_end`.
- Returns `±_REGION_PAD` lines with enclosing symbol metadata if different from the anchored region.

**`DeclaredIntentBuilder` (L684-732)**, `kind = "declared_intent"`:
- Emits two blocks: `preceding_lines` (up to `_REGION_PAD` lines before anchor) and `enclosing_head` (first `_ENCLOSING_HEAD_LINES` of enclosing symbol). Language-agnostic — no comment syntax awareness.

**`ShadowDocBuilder` (L764-870)**, `kind = "shadow_doc_claim"`:
- Source-anchored (file has shadow): emits file-scope evidence, plus directory-scope for `gap_type == "description"`.
- Doc-anchored (no file shadow + `gap_type == "description"`): resolves sources via `scanner_metadata.shadow_ref` + path-like `search_terms`, computes smallest scope via `_scope_for`.

**`TypeSignatureBuilder` (L873-889)**, `kind = "type_signature"`:
- Extracts PascalCase (non-all-caps) candidates from claim text + annotation-inferred types.
- Looks them up in symbols DB via `_lookup_type_definitions`.

### Registration (L892-903)
All five builder singletons are registered into `BUILDERS` (imported from `.evidence`) at module load time using `builder.kind` as the key.
