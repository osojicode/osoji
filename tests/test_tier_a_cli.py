"""osoji claims: zero-LLM Tier A entry point."""

import json

from click.testing import CliRunner

from osoji.cli import main


def _repo(temp_dir):
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    # A real `src/`: the anchor rule only decides path claims whose first
    # segment exists in the tree, and `src/missing.ts` is the contradicted
    # path claim this module asserts on.
    (temp_dir / "src").mkdir()
    (temp_dir / "src" / "index.ts").write_text("export {}\n", encoding="utf-8")
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


def test_audit_verifies_doc_claims_only_with_the_flag(temp_dir):
    _repo(temp_dir)
    excluded = ["--exclude", "shadow,doc-analysis,debris", "--no-gitignore"]

    default = CliRunner().invoke(main, ["audit", str(temp_dir), *excluded])
    assert "test:ui" not in default.output, default.output

    opted_in = CliRunner().invoke(main, ["audit", str(temp_dir), "--doc-claims", *excluded])
    assert opted_in.exit_code == 1, opted_in.output
    assert "test:ui" in opted_in.output
