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

### From obligation to verdict

Since V1-5b, an obligation carries no bespoke verification dataclass. Each `ConfigObligation` is adapted into a unified `Finding` (a reachability-gap hypothesis) by `finding_from_config_obligation` in `src/osoji/findings_adapter.py`, and the unified Triage stage fills the verdict (`confirmed` / `dismissed` / `uncertain`) with reasoning, confidence, and a suggested fix. The adapter frames the claim in *enforcement* terms and supplies the field name as the primary scan needle so the Claim Builder gathers the deciding cross-file references.

## Two-phase LLM pipeline

Dead plumbing detection uses a two-phase pipeline, each phase using a different LLM model tier to balance cost and reasoning depth: a cheap small-model proposal stage, then the shared medium-model Triage verdict.

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
|  Adapter + Claim Builder (no LLM) |
|  finding_from_config_obligation   |
|  + cross-file reference sweep     |
+-----------------------------------+
    |
    | Self-sufficient reachability   |
    | claims (field-name needles)    |
    v
+-----------------------------------+
|  Unified Triage (medium model)    |
|  Tool: submit_triage_verdicts     |
+-----------------------------------+
    |
    v
Confirmed JunkFindings (unactuated config)
```

### Phase A: Obligation extraction

Phase A uses a small/fast LLM model (`config.model_for("small")`) to scan schema files and identify obligation-bearing fields. The function `extract_obligations_async` sends each schema file's content and shadow documentation to the LLM with the `extract_obligations` tool.

The system prompt instructs the LLM to distinguish obligation-bearing fields from non-obligation fields. It specifically calls out that:

- Position/metadata fields (`line_start`, `line_end`, `offset`) are not obligations
- LLM tool schema constraints (`minimum`, `maximum`, `enum` in tool definitions) are not application obligations -- they constrain API output format, not application behavior
- Obligations must be textually stated in the schema (descriptions, comments, constraints), not inferred from field names alone
- Bare type declarations like `{"type": "integer"}` are not obligations

This phase is cheap: the small model processes one schema file per call, extracting structured data. The expense is justified because obligation extraction is fundamentally semantic -- a field named `http_deadline` and one named `request_timeout_ms` both bear timeout obligations, but only a language model can recognize this across naming conventions.

### Phase B: Actuation verdict (unified Triage)

Phase B uses the shared medium-model Triage stage. Each obligation becomes a reachability `Finding`; the mechanized Claim Builder (`src/osoji/evidence_builders.py`) assembles a self-sufficient claim by sweeping the repository for the field name (the primary needle) and the schema name, gathering the cross-file references, honest scan scope, and surrounding code that the deciding call needs. `decide_junk_claims` (`src/osoji/junk_triage.py`) then batches the claims through `Triage.decide_batch` under the unified `TRIAGE_SYSTEM_PROMPT`.

The rubric's *unactuated-config* clause encodes the actuation distinction that the retired `verify_actuation` prompt used to carry: a reference that only stores, forwards, restructures, or logs the value is not actuation and does not refute the gap; the field is alive only if some site uses its value to cause the declared effect. A cross-process handoff (env var -> container -> subprocess) counts when the receiving side enforces. This is why the generic "a real reference refutes reachability" rule is deliberately overridden for this gap type.

## What counts as actuation?

The unified rubric's unactuated-config clause defines a clear spectrum:

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

The `analyze_async` method delegates to `detect_dead_plumbing_async`, which returns all decided `Finding`s. It keeps only those with `verdict == "confirmed"` and re-wraps each into a `JunkFinding` (reading detector-specific fields such as `schema_name` back from the finding's `scanner_metadata`) with:

- `category="unactuated_config"` -- the finding category
- `kind="config_field"` -- the item kind
- `confidence_source="llm_inferred"` -- there is no mechanical fast path
- `metadata` containing `schema_name` and `trace` (now drawn from the Triage reasoning) for downstream rendering

The analyzer is registered in `JUNK_ANALYZERS` in `src/osoji/audit.py` alongside `DeadCodeAnalyzer`, `DeadParameterAnalyzer`, and the other junk analyzers.

## Design trade-offs

**Why two LLM calls instead of one?** Phase A is cheap filtering: the small model scans a schema file and produces a structured list of obligations. Phase B is expensive analysis: the medium-model Triage stage must reason about cross-file data flow using the assembled claim. Splitting the pipeline means the expensive Triage call only runs for genuine obligation-bearing fields, not for every field in every schema.

**Why LLM for obligation extraction instead of AST?** Obligations are semantic, not syntactic. A field named `request_timeout_ms` in a Python dataclass and a field named `httpDeadline` in a TypeScript interface both bear timeout obligations. AST parsing can extract field names and types, but cannot determine whether a field promises runtime enforcement. This aligns with Osoji's pipeline engineering principle of language agnosticism -- the detection works identically regardless of the schema's programming language.

**False positive risk.** Some actuations happen via dynamic dispatch or framework magic that a textual sweep may not capture. The confidence score on each confirmed `Finding` reflects the Triage stage's certainty, allowing downstream consumers to filter findings by confidence threshold.

**The cost of Phase B.** The Claim Builder bounds each claim's payload: the repo-wide reference sweep is capped (per-needle and per-file hit limits) and records honest scan scope, and the flagged schema file is always swept as minimum context. This keeps the medium-model Triage call within a fixed token budget while still gathering the consumer-site references that decide actuation.
