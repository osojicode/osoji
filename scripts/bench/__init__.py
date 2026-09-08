"""Documentation-drift benchmark tooling (osojicode/wiki specs/0005, Phase 0).

Mines docs-fix commits from open-source repositories into benchmark rows,
labels each row by partition / domain / kind / claim shape, and scores an
osoji run at the fix commit's parent against those rows. The data (rows,
labels, ``repos.toml`` with splits, spot-check sheets) lives in the private
repository ``osojicode/osoji-bench`` and is passed to these scripts as a
path (``--bench``, ``--rows``, ``--out``); nothing here is product code, and
nothing under this package ships in the wheel or the sdist.
"""
