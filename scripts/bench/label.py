"""Label mined benchmark rows with an LLM reader (wiki specs/0005, Phase 0.1).

Each row from ``bench.mine`` is one hunk group of a docs-only commit, seen
at the commit's parent. A reader decides whether the removed text asserted
something the parent repository contradicts (a *correction*), what the
truth of that claim depends on (decisions/0029's verification domains),
which PR #643 kind it is, and what the claim asserts (its *shape*, which is
what an extractor would have to recognise). One label per reader is kept,
so repeated runs build a panel; consensus is a separate step.

Usage:
    python scripts/bench/label.py --rows bench/<name>/rows.jsonl \
        --out bench/<name>/rows.labeled.jsonl --reader sonnet-r1 [--model M] [--limit N]

Resumable: rows already carrying a label from ``--reader`` are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from osoji.async_utils import gather_with_buffer
from osoji.config import Config
from osoji.llm.runtime import create_runtime
from osoji.llm.types import CompletionOptions, Message, MessageRole, ToolDefinition

PARTITIONS = ("correction", "deletion", "addition", "restructure", "generated", "other")
DOMAINS = ("checkout", "world", "runtime")
KINDS = (
    "false_statement", "nonexistent_artifact", "wrong_signature", "omission_from_list",
    "stale_pointer", "wrong_path", "wrong_count", "stale_version", "inverted_semantics",
    "wrong_command", "other",
)
CLAIM_SHAPES = ("path", "script", "symbol_signature", "behaviour", "enumeration", "value", "other")

LABEL_TOOL = ToolDefinition(
    name="label_doc_fix",
    description="Record the adjudication of one documentation-fix hunk group.",
    input_schema={
        "type": "object",
        "properties": {
            "partition": {"type": "string", "enum": list(PARTITIONS)},
            # osoji's tool validator takes single JSON types only, so "no
            # domain" is the explicit value "none" rather than a null union.
            "domain": {"type": "string", "enum": list(DOMAINS) + ["none"]},
            "kind": {"type": "string", "enum": list(KINDS)},
            "claim_shape": {"type": "string", "enum": list(CLAIM_SHAPES)},
            "claim": {
                "type": "string",
                "description": "One sentence: what the parent text asserted and what is actually true.",
            },
            "evidence_path": {
                "type": "string",
                "description": "Repository file most likely to decide the claim, or an empty string.",
            },
            "reasoning": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["partition", "kind", "claim_shape", "claim", "reasoning", "confidence"],
    },
)

SYSTEM_PROMPT = """You adjudicate one hunk group from a documentation-only commit in an open-source repository. You see the text the commit removed, the text it added, and the surrounding lines as they stood at the commit's PARENT. Your job is to say whether the removed text was a claim about the repository that was false at the parent, and to characterise that claim so a mechanical checker could be measured against it.

## partition — what kind of edit this was
- correction: the removed text asserted something the parent repository contradicts (a path, command, name, signature, count, default, or described behaviour that was not true of the code or tree at the parent).
- deletion: false text was removed without replacement. Counts as a correction of that text.
- addition: nothing removed was wrong; the edit only adds information.
- restructure: rewording, moving, reformatting, or renaming notation that preserves every claim; also removal of stale-but-not-false text.
- generated: tooling output (rendered tables, badges, generated indices).
- other: none of the above fits; say why in reasoning.

Principles: absence of detail is not a contradiction; a claim that became false because the world changed is still a correction of that text; a fix that changes only tone, tense, or style is a restructure.

## domain — what the claim's truth depends on (corrections and deletions; otherwise none)
- checkout: decidable by reading the repository at the parent commit (files, scripts, symbols, defaults, documented behaviour of the code in the tree).
- world: depends on facts outside the repository (a registry, a third-party tool's behaviour, an external service, release history).
- runtime: depends on observing the program run (performance figures, timings, environment-specific outcomes).
- none: the edit is not a correction, so no claim's truth is at stake.

## kind — the correction taxonomy
false_statement (a described behaviour or fact is wrong), nonexistent_artifact (names a file, script, command, symbol or option that does not exist), wrong_signature (parameters, types, return shape, or member names are wrong), omission_from_list (a list presented as complete omits a member the code has), stale_pointer (a reference to a location or name that moved), wrong_path (a path that is wrong but the artifact exists elsewhere), wrong_count (a number of items is wrong), stale_version (a version, date, or release requirement is wrong), inverted_semantics (says X where the truth is not-X), wrong_command (a command line that cannot work as written), other.

## claim_shape — what the claim asserts, in the checker's terms
path (a file or directory exists at a location), script (a command, script, or task target exists or is invoked in a stated way), symbol_signature (a symbol, member, parameter, option or type exists or has a stated shape), behaviour (what the code does, in prose), enumeration (a list, set, or count presented as complete), value (a default, version, number, or configuration value), other.

Write claim as one sentence in the document's own terms: what the parent text asserted, then what is actually true. Give evidence_path as the single repository file most likely to decide the claim, or an empty string. When torn between labels, choose other and explain. Call the label_doc_fix tool exactly once."""


def _numbered(lines: list[str], start: int, prefix: str) -> str:
    return "\n".join(f"{start + i:>5} {prefix}{line}" for i, line in enumerate(lines))


def build_messages(row: dict) -> tuple[str, str]:
    """Return (system, user) for one row."""

    before_start = row["old_start"] - len(row["context_before"])
    if row["old_len"] == 0 or not row["minus_text"]:
        before_start = row["old_start"] - len(row["context_before"]) + 1
    after_start = row["old_start"] + max(row["old_len"], 1)
    header = [
        f"Repository: {row['repo']}",
        f"Commit: {row['commit'][:12]} — {row['subject']}",
        f"Document: {row['path']}" + (f" (renamed to {row['renamed_to']})" if row.get("renamed_to") else ""),
        f"Old-side lines: {row['old_start']}–{row['old_start'] + max(row['old_len'], 1) - 1}"
        + (f" ({row['hunk_count']} hunks merged)" if row.get("hunk_count", 1) > 1 else ""),
    ]
    parts = ["\n".join(header), "", "Context before (parent):",
             _numbered(row["context_before"], max(before_start, 1), " "), "",
             "Removed at the parent:", _numbered(row["minus_text"], row["old_start"], "-"), "",
             "Added by the fix:", _numbered(row["plus_text"], row["new_start"], "+"), "",
             "Context after (parent):", _numbered(row["context_after"], after_start, " ")]
    return SYSTEM_PROMPT, "\n".join(parts)


def validate_label(data: dict) -> dict:
    """Coerce a tool payload into a label; unknown closed-set values route to ``other``."""

    claim = data.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("label has no claim")
    partition = data.get("partition")
    domain = data.get("domain")
    kind = data.get("kind")
    shape = data.get("claim_shape")
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    evidence = data.get("evidence_path")
    return {
        "partition": partition if partition in PARTITIONS else "other",
        "domain": domain if domain in DOMAINS else None,
        "kind": kind if kind in KINDS else "other",
        "claim_shape": shape if shape in CLAIM_SHAPES else "other",
        "claim": claim.strip(),
        "evidence_path": evidence.strip() if isinstance(evidence, str) and evidence.strip() else None,
        "reasoning": str(data.get("reasoning") or "").strip(),
        "confidence": max(0.0, min(1.0, confidence)),
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


async def label_rows(
    rows: list[dict], provider, config: Config, *, model: str, reader: str,
    out_path: Path, resume: bool = True, max_pending: int = 8,
) -> dict:
    """Label ``rows`` with ``reader`` and merge into ``out_path``. Returns counts."""

    existing = {r["row_id"]: r for r in _read_jsonl(out_path)}
    merged: list[dict] = []
    for row in rows:
        cur = existing.get(row["row_id"])
        merged.append(cur if cur is not None else dict(row))
    counts = {"labeled": 0, "failed": 0, "skipped": 0}

    async def one(row: dict) -> None:
        labels = row.get("labels") or {}
        if resume and reader in labels:
            counts["skipped"] += 1
            return
        system, user = build_messages(row)
        try:
            result = await provider.complete(
                messages=[Message(role=MessageRole.USER, content=user)],
                system=system,
                options=CompletionOptions(
                    model=model, max_tokens=1024, reservation_key="bench.label",
                    tools=[LABEL_TOOL], tool_choice={"type": "tool", "name": LABEL_TOOL.name},
                ),
            )
            call = next((tc for tc in result.tool_calls if tc.name == LABEL_TOOL.name), None)
            if call is None:
                raise ValueError("reader did not call label_doc_fix")
            label = validate_label(call.input)
        except Exception as exc:  # one bad row must not stop the batch
            counts["failed"] += 1
            if not config.quiet:
                print(f"  [fail] {row['row_id']}: {exc}", flush=True)
            return
        label["model"] = model
        label["labeled_at"] = datetime.now(timezone.utc).isoformat()
        row["labels"] = {**labels, reader: label}
        counts["labeled"] += 1

    try:
        await gather_with_buffer([lambda r=r: one(r) for r in merged], max_pending=max_pending)
    finally:
        _write_jsonl(out_path, merged)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--reader", required=True, help="label key, e.g. sonnet-r1")
    ap.add_argument("--model", default=None, help="model id; default = the medium tier")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--root", type=Path, default=Path("."), help="Config root (provider, .env, logs)")
    args = ap.parse_args()

    from dotenv import load_dotenv  # same convention as the CLI: .env never overrides the environment
    load_dotenv(args.root.resolve() / ".env")
    config = Config(root_path=args.root.resolve(), respect_gitignore=False)
    model = args.model or config.model_for("medium")
    rows = _read_jsonl(args.rows)
    if args.limit:
        rows = rows[: args.limit]

    async def run() -> dict:
        provider, _ = create_runtime(config)
        try:
            return await label_rows(rows, provider, config, model=model, reader=args.reader,
                                    out_path=args.out, resume=not args.no_resume)
        finally:
            await provider.close()

    counts = asyncio.run(run())
    print(json.dumps({"rows": len(rows), "reader": args.reader, "model": model, **counts}, indent=2))


if __name__ == "__main__":
    main()
