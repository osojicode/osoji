# Case 002: Internal Dataclass False Positives

## Edge Case

`audit.py` defines dataclasses (`AuditIssue`, `AuditResult`) that are only used within
the same file by functions (`run_audit`, `format_audit_report`, `format_audit_json`) that
ARE externally referenced (imported by `cli.py`).

The dataclasses have zero external references because no other file imports them directly.
However, they are transitively alive through the functions that use them.

## What Went Wrong

The scanner counted only external references, so within-file data types used by
externally-called functions appeared as zero-ref candidates. The LLM's tightened
decision rule ("used within the same file is NOT a valid reason") caused false positives.

## Fix

1. Scanner-level: Transitive liveness filter propagates aliveness from externally-referenced
   symbols to zero-ref symbols they reference within the same file
2. Prompt-level: Added "within-file transitive liveness" as a valid liveness pattern

## Ground Truth

- 0 dead symbols
- 2 alive dataclasses: AuditIssue, AuditResult (transitively alive via run_audit etc.)
