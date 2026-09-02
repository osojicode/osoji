"""osoji claims: zero-LLM Tier A entry point."""

import json

from click.testing import CliRunner

from osoji.cli import main


def _repo(temp_dir):
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    (temp_dir / "docs").mkdir()
    (temp_dir / "docs" / "guide.md").write_text(
        "Run `npm run build` then `npm run test:ui`. See `src/missing.ts`.\n", encoding="utf-8"
    )


def test_claims_text_reports_contradicted_and_exits_1(temp_dir):
    _repo(temp_dir)
    result = CliRunner().invoke(main, ["claims", str(temp_dir), "--no-gitignore"])
    assert result.exit_code == 1, result.output
    assert "test:ui" in result.output and "src/missing.ts" in result.output
    assert "npm run build" not in result.output  # supported claims hidden by default


def test_claims_json_all_lists_every_packet(temp_dir):
    _repo(temp_dir)
    result = CliRunner().invoke(main, ["claims", str(temp_dir), "--format", "json", "--all", "--no-gitignore"])
    data = json.loads(result.output)
    verdicts = sorted(p["verdict"] for p in data["packets"])
    assert verdicts == ["contradicted", "contradicted", "supported"]
    assert data["summary"]["contradicted"] == 2


def test_claims_clean_repo_exits_0(temp_dir):
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    (temp_dir / "README.md").write_text("Run `npm run build`.\n", encoding="utf-8")
    result = CliRunner().invoke(main, ["claims", str(temp_dir), "--no-gitignore"])
    assert result.exit_code == 0, result.output
