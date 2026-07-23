"""Console-script entry-point behavior (osoji#181).

Click 8 defaults to windows_expand_args=True, which glob-expands quoted
fnmatch option values (``--exclude "tests/*"``) into positional arguments on
Windows before parsing. The ``cli()`` wrapper must disable it.
"""

from osoji import cli as cli_module


def test_console_entry_disables_windows_glob_expansion(monkeypatch):
    captured: dict = {}

    def fake_group_main(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli_module.main, "main", fake_group_main)
    cli_module.cli()
    assert captured.get("windows_expand_args") is False


def test_pyproject_entry_point_targets_wrapper():
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads(
        (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["scripts"]["osoji"] == "osoji.cli:cli"
