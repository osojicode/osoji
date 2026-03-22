# Dead Plumbing Detection: Finding Config Fields That Never Reach Runtime

## What is dead plumbing?

Dead plumbing is a configuration field that is defined, parsed, stored, and threaded through your code -- but never actually *enforced*. The field exists in a schema, it has a name that promises a behavior, and users can set it to any value they like. But no code ever reads that value to cause the promised effect.

Consider these concrete examples:

- A `timeout_seconds` field in a settings schema. It is parsed from YAML, stored in a config dataclass, and passed through three layers of constructors. But no HTTP client, no `asyncio.wait_for`, no `setTimeout` ever receives the value. The user sets `timeout_seconds: 30`, and requests run indefinitely anyway.

- A `max_retries` field that appears in the configuration schema with a description saying "maximum number of retry attempts." The value is deserialized and stored on a config object, but the retry loop uses a hardcoded `3` instead of reading from config.

- A `rate_limit_rpm` field that is threaded from schema to config to constructor parameters. But the rate limiter reads a different field, or the rate limiter was removed, or the value is only logged for observability without ever being passed to an enforcement mechanism.

Dead plumbing is worse than dead code. A dead function is inert -- nobody calls it, and it harms nothing beyond codebase clutter. Dead plumbing actively misleads: it gives users the *illusion* of control. When a user sets `timeout_seconds: 5` and finds that requests still hang for minutes, the debugging experience is painful because the configuration appears to be correct.

## The obligation model

The detection system in `src/osoji/plumbing.py` is built around two core data structures.

### ConfigObligation

A `ConfigObligation` represents a schema field that *declares a behavioral obligation* -- a promise that the system will enforce a runtime behavior. It carries:

| Field                | Purpose                                              |
| -------------------- | ---------------------------------------------------- |
| `source_path`        | File defining the schema                             |
| `field_name`         | The config field (e.g., `taskTimeoutMs`)              |
| `schema_name`        | The containing schema (e.g., `TrialSettingsSchema`)   |
| `line_start`/`line_end` | Location in source                                |
| `obligation`         | What the field promises ("controls request timeout")  |
| `expected_actuation` | What enforcement code would look like                 |
| `evidence`           | Direct quote from schema text grounding the obligation|

Not all config fields are obligations. Identity fields (`name`, `id`), data shape fields (`type`, `format`), descriptive fields (`status`, `result`), and position/metadata fields (`line_start`, `offset`) do not bear behavioral obligations. The extraction phase filters these out.

### PlumbingVerification

A `PlumbingVerification` records whether an obligation is met:

| Field          | Purpose                                              |
| -------------- | ---------------------------------------------------- |
| `is_actuated`  | Whether the field value reaches an enforcement point  |
| `confidence`   | How certain the verification is (0.0-1.0)             |
| `trace`        | Description of the data flow (or where the gap is)    |
| `remediation`  | Suggested fix if unactuated                           |

## Two-phase LLM pipeline

Dead plumbing detection uses a two-phase pipeline, each phase using a different LLM model tier to balance cost and reasoning depth.

```
Schema files (role="schema")
    |
    v
+-----------------------------------+
|  Phase A: Obligation extraction   |
|  (small/fast model)               |
|  Tool: extract_obligations        |
+-----------------------------------+
    |
    | List of ConfigObligation
    v
+-----------------------------------+
|  Reference scanning (no LLM)     |
|  _find_field_references()         |
+-----------------------------------+
    |
    | Per-obligation: referencing    |
    | file paths + shadow docs       |
    v
+-----------------------------------+
|  Phase B: Actuation verification  |
|  (medium model)                   |
|  Tool: verify_actuation           |
+-----------------------------------+
    |
    v
PlumbingResult (unactuated findings)
```

### Phase A: Obligation extraction

Phase A uses a small/fast LLM model (`config.model_for("small")`) to scan schema files and identify obligation-bearing fields. The function `extract_obligations_async` sends each schema file's content and shadow documentation to the LLM with the `extract_obligations` tool.

The system prompt instructs the LLM to distinguish obligation-bearing fields from non-obligation fields. It specifically calls out that:

- Position/metadata fields (`line_start`, `line_end`, `offset`) are not obligations
- LLM tool schema constraints (`minimum`, `maximum`, `enum` in tool definitions) are not application obligations -- they constrain API output format, not application behavior
- Obligations must be textually stated in the schema (descriptions, comments, constraints), not inferred from field names alone
- Bare type declarations like `{"type": "integer"}` are not obligations

This phase is cheap: the small model processes one schema file per call, extracting structured data. The expense is justified because obligation extraction is fundamentally semantic -- a field named `http_deadline` and one named `request_timeout_ms` both bear timeout obligations, but only a language model can recognize this across naming conventions.

### Phase B: Actuation verification

Phase B uses a medium model (`config.model_for("medium")`) because it requires deeper reasoning about data flow across files. For each obligation extracted in Phase A, `verify_actuation_async` provides the LLM with:

1. **The obligation details** -- field name, schema name, what it promises, and what enforcement would look like.

2. **Schema shadow doc** -- the shadow documentation for the file defining the schema, excerpted around the field name using `_shadow_excerpt` with a configurable context radius (`_SHADOW_CONTEXT_RADIUS = 12` lines).

3. **Referencing file shadows** -- shadow docs for all files that textually reference the field name (found by `_find_field_references`, which performs a regex scan across the repository). Up to `_MAX_REFERENCING_SHADOWS = 12` are included, prioritizing non-test files via `_select_shadow_excerpts`.

4. **Sibling field shadows** -- shadow docs showing how *other* obligation-bearing fields from the same schema are used. These serve as positive counterexamples: if `timeout` is actuated but `max_retries` is not, the contrast helps the LLM identify the gap. Up to `_MAX_SIBLING_SHADOWS = 6` are included.

The LLM uses the `verify_actuation` tool to render its verdict: actuated, not actuated, or uncertain.

## What counts as actuation?

The system prompt defines a clear spectrum:

**Clear actuation** -- the field value is passed to a mechanism that enforces the declared behavior:
- `setTimeout(callback, field)` -- actuation via timer
- `if (turns >= field) break` -- actuation via loop guard
- `axios({timeout: field})` -- actuation via library enforcement
- Passing as an environment variable to a container whose shadow doc confirms enforcement

**Not actuation** -- the field value is accessed but never enforced:
- Logging the value (`logger.info(f"timeout={field}")`)
- Storing in results or metrics
- Including in a config object that is only read by other config code
- Displaying in a UI

The distinction is between *observing* a value and *enforcing* it. A field that is logged, validated, and serialized but never passed to an actuator is dead plumbing.

## Integration with the junk code framework

`DeadPlumbingAnalyzer` implements the `JunkAnalyzer` ABC from `src/osoji/junk.py`:

| Property     | Value                                    |
| ------------ | ---------------------------------------- |
| `name`       | `"dead_plumbing"`                        |
| `description`| `"Detect unactuated config obligations"` |
| `cli_flag`   | `"dead-plumbing"`                        |

The `analyze_async` method delegates to `detect_dead_plumbing_async`, then converts unactuated `PlumbingVerification` objects into `JunkFinding` instances with:

- `category="unactuated_config"` -- the finding category
- `kind="config_field"` -- the item kind
- `metadata` containing `schema_name` and `trace` for downstream rendering

The analyzer is registered in `JUNK_ANALYZERS` in `src/osoji/audit.py` alongside `DeadCodeAnalyzer`, `DeadParameterAnalyzer`, and the other junk analyzers.

## Design trade-offs

**Why two LLM calls instead of one?** Phase A is cheap filtering: the small model scans a schema file and produces a structured list of obligations. Phase B is expensive analysis: the medium model must reason about cross-file data flow using shadow docs from multiple files. Splitting the pipeline means the expensive Phase B only runs for genuine obligation-bearing fields, not for every field in every schema.

**Why LLM for obligation extraction instead of AST?** Obligations are semantic, not syntactic. A field named `request_timeout_ms` in a Python dataclass and a field named `httpDeadline` in a TypeScript interface both bear timeout obligations. AST parsing can extract field names and types, but cannot determine whether a field promises runtime enforcement. This aligns with Osoji's pipeline engineering principle of language agnosticism -- the detection works identically regardless of the schema's programming language.

**False positive risk.** Some actuations happen via dynamic dispatch or framework magic that shadow docs may not capture. The confidence score on each `PlumbingVerification` reflects the LLM's certainty, allowing downstream consumers to filter findings by confidence threshold.

**The cost of Phase B.** Each obligation requires loading shadow docs for all referencing files plus sibling fields. The `_select_shadow_excerpts` function manages this by capping the number of included shadows and truncating each to `_MAX_SHADOW_EXCERPT_CHARS = 2000` characters, focused around the relevant field name. A shared `file_content_cache` dictionary avoids redundant file reads across obligations from the same schema.
