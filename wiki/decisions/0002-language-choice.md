---
id: "0002"
title: Language choice — Python (with a sidecar door open)
type: decision
status: accepted
created: 2026-04-29
updated: 2026-04-29
related: [specs/0001-v1-foundation.md]
---

## Context

The v1 foundation rebuild ([spec 0001](../specs/0001-v1-foundation.md)) is large enough that it is fair to ask whether it should also be a language change. The candidate alternatives discussed (in conversation, prior to this wiki existing) included Rust (for AST/facts performance and tree-sitter native bindings), Go (for deployability and concurrency primitives), and TypeScript (to share types with the dashboard).

## Decision

**Stay on Python for v1.**

## Reasons

1. **The hot path is the LLM call, not the AST work.** Every other concern is downstream of latency to the model. Optimizing the AST layer in a faster language would shave milliseconds off something that takes seconds.
2. **`py-tree-sitter` is fast enough.** Tree-sitter has first-class Python bindings; the planned migration ([spec 0001 §tree-sitter substrate](../specs/0001-v1-foundation.md#tree-sitter-substrate-e-in-earlier-discussion)) does not require leaving Python.
3. **The Finding schema will evolve.** Python's type-as-aspiration (dataclasses, runtime-checked typing, easy schema migration) makes the iteration cheap. A statically-typed compiled language would slow this down precisely where speed matters most.
4. **The OSS scanner ecosystem we want to absorb in v2 is largely Python-native.** semgrep, bandit, ruff, pip-audit — all Python-callable or Python-implemented. The Finding schema bridge to these tools is one Python import away.
5. **No measurement-justified bottleneck.** Don't speculate: pick the language that minimizes friction now and only switch when a measured constraint forces the switch.

## Sidecar door left open

If/when AST/facts becomes the measured bottleneck — likely only after the corpus grows past O(10k) pages or osoji is run on monorepos with O(100k) files — extract the AST/facts work to a Rust sidecar that emits JSON across the [Finding schema](../specs/0001-v1-foundation.md#the-finding-schema-a) boundary that already exists. The schema is the contract; the language behind it is implementation detail.

This means: any v1 code that touches AST/facts must keep its boundary clean enough that swapping the implementation does not require rewriting consumers. The Finding/Evidence schema, not in-process Python objects, is the cross-boundary contract.

## Alternatives considered (briefly)

- **Rust + py-tree-sitter rewrite.** Rejected: invests in a non-bottleneck.
- **Go.** Rejected: would force a complete rewrite of the LLM provider layer (`src/osoji/llm/`) for no measured benefit.
- **TypeScript.** Rejected: AST/facts work in TS would be slower than Python with `py-tree-sitter`, and the shared-types-with-dashboard argument is solved by the JSON Schema (`src/osoji/osoji-observatory.schema.json`) we already maintain.

## Reversibility

This decision is reversible at the schema boundary. If a future v2 or v3 makes the case for sidecar extraction or full rewrite, the Finding/Evidence schema is what survives.
