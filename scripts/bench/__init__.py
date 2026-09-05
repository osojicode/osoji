"""Documentation-drift benchmark tooling (osojicode/wiki specs/0005, Phase 0).

Mines docs-fix commits from open-source repositories into benchmark rows,
labels each row by partition / domain / kind / claim shape, and scores an
osoji run at the fix commit's parent against those rows. Data lives under
``bench/<repo>/``; nothing here is product code.
"""
