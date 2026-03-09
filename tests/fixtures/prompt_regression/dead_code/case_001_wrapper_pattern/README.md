# Case 001: Wrapper Pattern False Negatives

## Commit
d9eaec6 (main, 2026-02-24)

## Edge Case
`tools.py` contains both TOOL constant dicts (alive — imported via `_tool_definitions`
variants by consumer modules) and `get_*_tools()` wrapper functions (dead — zero references).

The dead functions are simple wrappers that return lists containing the alive constants:
```python
def get_file_tools() -> list[dict]:
    return [SUBMIT_SHADOW_DOC_TOOL]
```

## What Went Wrong
When batched with the alive constants, the LLM saw that `get_file_tools()` returns
`[SUBMIT_SHADOW_DOC_TOOL]` (which IS used), and inferred the function must be an
"alternative access path." Only 2 of 7 identical dead functions were caught.

## Fix
Added explicit decision rule to the dead code verification prompt:
- "It wraps a symbol that is used" is NOT a valid reason to keep alive
- If the wrapper itself has zero references, it's dead regardless

## Ground Truth
- 7 dead `get_*_tools()` functions (wrappers with zero external references)
- 8 alive TOOL constants (referenced by `_tool_definitions` variants in consumer files)
- 8 alive `get_*_tool_definitions()` functions (imported by consumer modules)
