"""Integration tests for extract.js — requires real Node.js + ts-morph.

These tests write actual .ts files to disk, run extract.js via subprocess,
and validate the JSON output.  Skipped when Node.js or ts-morph is not
installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_EXTRACT_JS = Path(__file__).resolve().parent.parent / "src" / "osoji" / "plugins" / "ts_runner" / "extract.js"

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_has_node = shutil.which("node") is not None


def _has_ts_morph() -> bool:
    if not _has_node:
        return False
    try:
        subprocess.run(
            ["node", "-e", "require('ts-morph')"],
            capture_output=True,
            timeout=10,
            check=True,
        )
        return True
    except Exception:
        return False


_ts_morph_available = _has_ts_morph()

pytestmark = pytest.mark.skipif(
    not (_has_node and _ts_morph_available),
    reason="Node.js and ts-morph required for integration tests",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_tsconfig(root: Path) -> Path:
    """Create a minimal tsconfig.json that covers all .ts files under root."""
    tsconfig = root / "tsconfig.json"
    tsconfig.write_text(
        json.dumps({
            "compilerOptions": {
                "target": "ES2020",
                "module": "commonjs",
                "strict": True,
                "esModuleInterop": True,
                "outDir": "./dist",
                "rootDir": ".",
            },
            "include": ["./**/*.ts"],
        }),
        encoding="utf-8",
    )
    return tsconfig


def _run_extract(root: Path, files: list[str], tsconfigs: list[Path] | None = None) -> dict:
    """Run extract.js and return parsed JSON output."""
    if tsconfigs is None:
        tsconfigs = [root / "tsconfig.json"]
    cmd = ["node", str(_EXTRACT_JS)] + [str(tc) for tc in tsconfigs]
    stdin_payload = json.dumps({"files": files, "workspacePackages": {}})
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        input=stdin_payload,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        pytest.fail(f"extract.js failed (exit {proc.returncode}):\n{proc.stderr}")
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_basic_extraction(tmp_path):
    """Function + variable exports, imports, calls."""
    _write_tsconfig(tmp_path)

    (tmp_path / "app.ts").write_text(
        'import { helper } from "./lib";\n'
        "export function main() { helper(); }\n"
        "export const VERSION = 1;\n",
        encoding="utf-8",
    )
    (tmp_path / "lib.ts").write_text(
        "export function helper() { return 42; }\n",
        encoding="utf-8",
    )

    out = _run_extract(tmp_path, ["app.ts", "lib.ts"])

    # app.ts
    app = out["app.ts"]
    assert any(e["name"] == "main" and e["kind"] == "function" for e in app["exports"])
    assert any(e["name"] == "VERSION" and e["kind"] == "variable" for e in app["exports"])
    assert any(i["source"] == "./lib" for i in app["imports"])
    assert any(c["to"] == "helper" for c in app["calls"])

    # lib.ts
    lib = out["lib.ts"]
    assert any(e["name"] == "helper" for e in lib["exports"])


def test_class_method_exports(tmp_path):
    """Public method exports as Class.method."""
    _write_tsconfig(tmp_path)

    (tmp_path / "service.ts").write_text(
        "export class UserService {\n"
        "  findAll() { return []; }\n"
        "  private secret() {}\n"
        "  protected internal() {}\n"
        "}\n",
        encoding="utf-8",
    )

    out = _run_extract(tmp_path, ["service.ts"])
    exports = out["service.ts"]["exports"]
    export_names = [e["name"] for e in exports]

    assert "UserService" in export_names
    assert "UserService.findAll" in export_names
    # Private and protected should be excluded
    assert "UserService.secret" not in export_names
    assert "UserService.internal" not in export_names


def test_framework_decorators(tmp_path):
    """Decorator detection sets exclude_from_dead_analysis."""
    _write_tsconfig(tmp_path)

    (tmp_path / "controller.ts").write_text(
        "function Controller() { return (t: any) => t; }\n"
        "function Get() { return (t: any, k: string) => {}; }\n"
        "@Controller()\n"
        "export class AppController {\n"
        "  @Get()\n"
        "  index() { return 'ok'; }\n"
        "}\n",
        encoding="utf-8",
    )

    out = _run_extract(tmp_path, ["controller.ts"])
    exports = out["controller.ts"]["exports"]

    cls_export = next(e for e in exports if e["name"] == "AppController")
    assert cls_export["exclude_from_dead_analysis"] is True
    assert "Controller" in cls_export["decorators"]

    method_export = next(e for e in exports if e["name"] == "AppController.index")
    assert method_export["exclude_from_dead_analysis"] is True


def test_parameter_extraction(tmp_path):
    """Function parameters are extracted."""
    _write_tsconfig(tmp_path)

    (tmp_path / "util.ts").write_text(
        "export function greet(name: string, loud?: boolean): string {\n"
        "  return loud ? name.toUpperCase() : name;\n"
        "}\n",
        encoding="utf-8",
    )

    out = _run_extract(tmp_path, ["util.ts"])
    exp = next(e for e in out["util.ts"]["exports"] if e["name"] == "greet")
    assert "parameters" in exp
    params = exp["parameters"]
    assert len(params) == 2
    assert params[0]["name"] == "name"
    assert params[0]["optional"] is False
    assert params[1]["name"] == "loud"
    assert params[1]["optional"] is True


def test_constructor_calls(tmp_path):
    """new Class() appears in calls."""
    _write_tsconfig(tmp_path)

    (tmp_path / "app.ts").write_text(
        "export class Foo {}\n"
        "export function create() { return new Foo(); }\n",
        encoding="utf-8",
    )

    out = _run_extract(tmp_path, ["app.ts"])
    calls = out["app.ts"]["calls"]
    assert any(c["to"] == "Foo" for c in calls)


def test_scope_qualified_from_symbol(tmp_path):
    """Calls inside class methods get ClassName.methodName as from_symbol."""
    _write_tsconfig(tmp_path)

    (tmp_path / "svc.ts").write_text(
        "function doWork() {}\n"
        "export class Svc {\n"
        "  run() { doWork(); }\n"
        "}\n",
        encoding="utf-8",
    )

    out = _run_extract(tmp_path, ["svc.ts"])
    calls = out["svc.ts"]["calls"]
    do_work_call = next((c for c in calls if c["to"] == "doWork"), None)
    assert do_work_call is not None
    assert do_work_call["from_symbol"] == "Svc.run"


def test_star_reexport(tmp_path):
    """export * from creates reexport import with names=['*']."""
    _write_tsconfig(tmp_path)

    (tmp_path / "types.ts").write_text(
        "export interface User { name: string; }\n",
        encoding="utf-8",
    )
    (tmp_path / "index.ts").write_text(
        'export * from "./types";\n',
        encoding="utf-8",
    )

    out = _run_extract(tmp_path, ["index.ts", "types.ts"])
    idx_imports = out["index.ts"]["imports"]
    star = next((i for i in idx_imports if "*" in i["names"]), None)
    assert star is not None
    assert star["is_reexport"] is True
    assert star["source"] == "./types"


def test_cross_file_call_resolution(tmp_path):
    """Two-file test: call_sites counted across files via import resolution."""
    _write_tsconfig(tmp_path)

    (tmp_path / "lib.ts").write_text(
        "export function helper() { return 1; }\n",
        encoding="utf-8",
    )
    (tmp_path / "main.ts").write_text(
        'import { helper } from "./lib";\n'
        "export function run() { helper(); helper(); }\n",
        encoding="utf-8",
    )

    out = _run_extract(tmp_path, ["lib.ts", "main.ts"])

    # Both calls to helper in main.ts should resolve to lib.ts::helper
    main_calls = out["main.ts"]["calls"]
    helper_calls = [c for c in main_calls if c["to"] == "helper"]
    assert len(helper_calls) == 2
    # All should have the same cross-file call_sites count (2)
    for c in helper_calls:
        assert c["call_sites"] == 2


def test_backward_compat_array_input(tmp_path):
    """Old array-of-files stdin format still works."""
    _write_tsconfig(tmp_path)

    (tmp_path / "simple.ts").write_text(
        "export const X = 42;\n",
        encoding="utf-8",
    )

    tsconfig = tmp_path / "tsconfig.json"
    cmd = ["node", str(_EXTRACT_JS), str(tsconfig)]
    # Send plain array (old format)
    stdin_payload = json.dumps(["simple.ts"])
    proc = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        input=stdin_payload,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"extract.js failed:\n{proc.stderr}"
    out = json.loads(proc.stdout)
    assert "simple.ts" in out
    assert any(e["name"] == "X" for e in out["simple.ts"]["exports"])


def test_import_resolved_path(tmp_path):
    """resolved_path is set on imports pointing to project files."""
    _write_tsconfig(tmp_path)

    (tmp_path / "utils.ts").write_text(
        "export function util() {}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.ts").write_text(
        'import { util } from "./utils";\n'
        "util();\n",
        encoding="utf-8",
    )

    out = _run_extract(tmp_path, ["main.ts", "utils.ts"])
    imp = next(i for i in out["main.ts"]["imports"] if i["source"] == "./utils")
    assert "resolved_path" in imp
    # Should be a relative path ending in utils.ts
    assert imp["resolved_path"].endswith("utils.ts")
