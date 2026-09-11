"""The TypeScript plugin's structure extractor, end to end through Node when it is available.

Everything the code-claim registries need is checked on one small fixture: enum members,
interface members with optional flags and parameter counts, class members including
constructor parameter properties, `implements`/`extends`, object-literal exports with their
annotation, function parameters with type references or inline literals, member references
with optional-call flags, calls with object-literal argument keys and receivers, and typed
locals. The mocked test below pins the subprocess contract without Node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from osoji.plugins.typescript_plugin import TypeScriptPlugin, _STRUCTURE_RUNNER

_RUNNER_HAS_TS_MORPH = (_STRUCTURE_RUNNER.parent / "node_modules" / "ts-morph").is_dir()
needs_node = pytest.mark.skipif(
    not shutil.which("node") or not _RUNNER_HAS_TS_MORPH,
    reason="node and ts-morph (scripts/ts_runner/node_modules) are required",
)

_FIXTURE = """
import { SessionState, type AdapterPolicy } from '@acme/shared';
import { EventEmitter } from 'events';
import { helper } from './util.js';

export enum Colour { RED = 'red', BLUE = 'blue' }

export interface IProcess { pid: number; kill(signal?: string): void }
export interface IProxyProcess extends IProcess {
  sessionId: string;
  sendCommand(command: object): void;
  onProxyStatus(status: string, message: unknown): void;
  extra?: number;
}

class FakeProxyProcess extends EventEmitter implements IProxyProcess {
  pid = 1;
  constructor(public readonly sessionId: string) { super(); }
  kill(): void {}
  sendCommand(command: object): void {}
  onProxyStatus(status: string): void {}
}

export const DefaultPolicy: AdapterPolicy = { name: 'default', isReady(s: SessionState) { return false; } };
export const Other = { a: 1, ...DefaultPolicy };

export function createSession(params: { language: string; executablePath?: string }): void {}
export async function transform(config: AdapterPolicy, ...rest: number[]): Promise<void> {}

let manager: FakeProxyProcess;
manager = new FakeProxyProcess('s');
const other = new FakeProxyProcess('t');

function run() {
  const x = SessionState.IDLE;
  DefaultPolicy.updateStateOnCommand?.('a', {}, {});
  manager.sendCommand({ command: 'x', extra: true });
  createSession({ language: 'py', pythonPath: '/x' });
  helper({ ...other });
}
"""


@needs_node
def test_structure_extraction_end_to_end(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ts").write_text(_FIXTURE, encoding="utf-8")
    facts = TypeScriptPlugin().extract_structure(tmp_path, [src / "a.ts"])

    f = facts["src/a.ts"]
    specs = {i["specifier"]: i for i in f["imports"]}
    assert specs["@acme/shared"]["names"] == ["SessionState", "AdapterPolicy"]
    assert specs["./util.js"]["names"] == ["helper"] and specs["./util.js"]["line"] == 4

    decls = {d["name"]: d for d in f["declarations"]}
    assert [m["name"] for m in decls["Colour"]["members"]] == ["RED", "BLUE"] and decls["Colour"]["kind"] == "enum"

    proxy = decls["IProxyProcess"]
    assert proxy["extends"] == ["IProcess"]
    members = {m["name"]: m for m in proxy["members"]}
    assert members["sessionId"]["optional"] is False and members["extra"]["optional"] is True
    assert members["onProxyStatus"]["required_params"] == 2 and members["sendCommand"]["required_params"] == 1
    assert members["onProxyStatus"]["signature"] == "onProxyStatus(status: string, message: unknown): void"

    fake = decls["FakeProxyProcess"]
    assert fake["exported"] is False and fake["extends"] == ["EventEmitter"] and fake["implements"] == ["IProxyProcess"]
    fake_members = {m["name"]: m for m in fake["members"]}
    assert fake_members["sessionId"]["kind"] == "property"          # constructor parameter property
    assert fake_members["onProxyStatus"]["required_params"] == 1
    assert fake_members["kill"]["required_params"] == 0

    policy = decls["DefaultPolicy"]
    assert policy["kind"] == "object" and policy["annotation"] == "AdapterPolicy"
    assert [m["name"] for m in policy["members"]] == ["name", "isReady"] and policy["open"] is False
    assert decls["Other"]["open"] is True                              # spread

    params = decls["createSession"]["params"]
    assert params[0]["members"] == ["language", "executablePath"] and params[0]["open"] is False
    transform = decls["transform"]["params"]
    assert transform[0]["type"] == "AdapterPolicy" and transform[1]["rest"] is True

    refs = {(r["object"], r["member"]): r for r in f["member_refs"]}
    assert refs[("SessionState", "IDLE")]["call"] is False
    hook = refs[("DefaultPolicy", "updateStateOnCommand")]
    assert hook["optional"] is True and hook["call"] is True

    calls = {c["member"]: c for c in f["calls"]}
    assert calls["sendCommand"]["receiver"] == "manager" and calls["sendCommand"]["args"][0]["keys"] == ["command", "extra"]
    assert calls["createSession"]["receiver"] is None and calls["createSession"]["args"][0]["keys"] == ["language", "pythonPath"]
    assert calls["helper"]["args"][0]["spread"] is True

    locals_ = {(l["name"], l["type"]) for l in f["locals"]}
    assert ("manager", "FakeProxyProcess") in locals_ and ("other", "FakeProxyProcess") in locals_


def test_module_candidates_follow_the_esm_mapping():
    p = TypeScriptPlugin()
    assert p.module_candidates("src/a.js")[:3] == ["src/a.ts", "src/a.tsx", "src/a.d.ts"]
    assert p.module_candidates("src/a.mjs")[0] == "src/a.mts"
    assert "src/dir/index.ts" in p.module_candidates("src/dir")
    assert p.module_candidates("src/data.json") == ["src/data.json"]


def test_extract_structure_runs_the_structure_runner_and_parses_its_json(tmp_path):
    plugin = TypeScriptPlugin()
    (tmp_path / "a.ts").write_text("export const x = 1;\n", encoding="utf-8")
    mock_proc = MagicMock(returncode=0, stdout=json.dumps({"a.ts": {"imports": [], "declarations": []}}), stderr="")
    with patch.object(plugin, "check_available"), \
         patch("osoji.plugins.typescript_plugin.subprocess.run", return_value=mock_proc) as run:
        facts = plugin.extract_structure(tmp_path, [tmp_path / "a.ts", tmp_path / "b.py"])
    assert facts == {"a.ts": {"imports": [], "declarations": []}}
    argv, kwargs = run.call_args
    assert argv[0][:2] == ["node", str(_STRUCTURE_RUNNER)]
    assert json.loads(kwargs["input"]) == {"files": ["a.ts"]}


def test_extract_structure_surfaces_runner_failures(tmp_path):
    from osoji.plugins.base import FactsExtractionError

    plugin = TypeScriptPlugin()
    (tmp_path / "a.ts").write_text("", encoding="utf-8")
    with patch.object(plugin, "check_available"), \
         patch("osoji.plugins.typescript_plugin.subprocess.run",
               return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
        with pytest.raises(FactsExtractionError, match="boom"):
            plugin.extract_structure(tmp_path, [tmp_path / "a.ts"])
    with patch.object(plugin, "check_available"), \
         patch("osoji.plugins.typescript_plugin.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="node", timeout=1)):
        with pytest.raises(FactsExtractionError, match="timed out"):
            plugin.extract_structure(tmp_path, [tmp_path / "a.ts"])
