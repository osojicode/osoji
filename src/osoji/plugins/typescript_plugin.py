"""TypeScript language plugin — extraction via ts-morph (Node.js subprocess)."""

from __future__ import annotations

import glob as glob_mod
import json
import os
import shutil
import subprocess
from pathlib import Path

from .base import ExtractedFacts, FactsExtractionError, LanguagePlugin, PluginUnavailableError

_TS_RUNNER = Path(__file__).parent / "ts_runner" / "extract.js"

# Directories to skip when searching for tsconfig files.
_EXCLUDE_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage"}


def _find_all_tsconfigs(project_root: Path, files: list[Path] | None = None) -> list[Path]:
    """Find tsconfig.json files relevant to the project.

    When *files* is provided (the walker-filtered file list), we derive
    tsconfigs from the directories that actually contain source files.
    This avoids picking up hundreds of irrelevant tsconfigs from gitignored
    ``data/`` or experiment directories.
    """
    if files:
        # Collect unique directories containing TS files, then walk up
        # from each toward project_root looking for a tsconfig.json.
        seen: set[Path] = set()
        tsconfigs: list[Path] = []
        for f in files:
            current = f.parent
            while current >= project_root:
                if current in seen:
                    break
                seen.add(current)
                candidate = current / "tsconfig.json"
                if candidate.is_file() and candidate not in seen:
                    seen.add(candidate)
                    tsconfigs.append(candidate)
                current = current.parent
        return tsconfigs

    # Fallback: walk the whole tree (no file list available).
    tsconfigs = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
        if "tsconfig.json" in filenames:
            tsconfigs.append(Path(dirpath) / "tsconfig.json")
    return tsconfigs


def _detect_workspace_packages(project_root: Path) -> dict[str, str]:
    """Detect monorepo workspace packages and return ``{name: relative_src_dir}``."""
    workspace_dirs: list[str] = []

    # Check pnpm-workspace.yaml
    pnpm_ws = project_root / "pnpm-workspace.yaml"
    if pnpm_ws.is_file():
        try:
            import yaml  # optional dependency

            data = yaml.safe_load(pnpm_ws.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "packages" in data:
                workspace_dirs.extend(data["packages"])
        except ImportError:
            # Fallback: simple line parsing
            for line in pnpm_ws.read_text(encoding="utf-8").splitlines():
                stripped = line.strip().lstrip("- ").strip("'\"")
                if stripped and not stripped.startswith("#") and not stripped.startswith("packages"):
                    workspace_dirs.append(stripped)
        except Exception:
            pass

    # Check package.json workspaces (only if pnpm didn't yield anything)
    if not workspace_dirs:
        pkg_json = project_root / "package.json"
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                ws = data.get("workspaces", [])
                if isinstance(ws, list):
                    workspace_dirs = ws
                elif isinstance(ws, dict) and "packages" in ws:
                    workspace_dirs = ws["packages"]
            except Exception:
                pass

    if not workspace_dirs:
        return {}

    # Resolve globs to actual directories and read package names
    packages: dict[str, str] = {}
    for pattern in workspace_dirs:
        for match in glob_mod.glob(str(project_root / pattern)):
            match_path = Path(match)
            match_pkg_json = match_path / "package.json"
            if match_pkg_json.is_file():
                try:
                    data = json.loads(match_pkg_json.read_text(encoding="utf-8"))
                    name = data.get("name")
                    if name:
                        # Prefer src/ sub-dir if it exists, else package root
                        src_dir = match_path / "src"
                        rel = str(
                            (src_dir if src_dir.is_dir() else match_path).relative_to(
                                project_root
                            )
                        ).replace("\\", "/")
                        packages[name] = rel
                except Exception:
                    pass

    return packages


class TypeScriptPlugin(LanguagePlugin):
    """TypeScript AST extraction using ts-morph via Node.js subprocess."""

    @property
    def name(self) -> str:
        return "typescript"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".ts", ".tsx", ".mts"})

    def check_available(self, project_root: Path) -> None:
        if not shutil.which("node"):
            raise PluginUnavailableError(
                "Node.js not found",
                "Install Node.js: https://nodejs.org",
            )

        ts_runner_dir = Path(__file__).parent / "ts_runner"

        # Check if ts-morph is available from the runner's own node_modules
        # or from the target project.
        check = subprocess.run(
            ["node", "-e",
             "try { require(require('path').join("
             f"'{ts_runner_dir.as_posix()}', 'node_modules', 'ts-morph')) }}"
             " catch(_) { require('ts-morph') }"],
            cwd=str(project_root),
            capture_output=True,
            timeout=10,
        )
        if check.returncode == 0:
            return

        # Auto-install ts-morph in the runner directory
        npm = shutil.which("npm")
        if not npm:
            raise PluginUnavailableError(
                "ts-morph not found and npm not available to install it",
                "Install Node.js (includes npm): https://nodejs.org",
            )
        install = subprocess.run(
            [npm, "install", "--no-audit", "--no-fund"],
            cwd=str(ts_runner_dir),
            capture_output=True,
            timeout=120,
        )
        if install.returncode != 0:
            raise PluginUnavailableError(
                "Failed to install ts-morph",
                f"Run manually: cd {ts_runner_dir} && npm install",
            )

    def extract_project_facts(
        self, project_root: Path, files: list[Path]
    ) -> dict[str, ExtractedFacts]:
        self.check_available(project_root)

        # Find all tsconfigs for monorepo support (scoped to actual source files)
        ts_file_paths = [f for f in files if f.suffix in self.extensions]
        tsconfigs = _find_all_tsconfigs(project_root, ts_file_paths)
        if not tsconfigs:
            # Fallback: walk up from project_root (legacy single-tsconfig path)
            tsconfig = self._find_tsconfig(project_root)
            if not tsconfig:
                raise FactsExtractionError(
                    f"No tsconfig.json found at or under {project_root}"
                )
            tsconfigs = [tsconfig]

        # Filter to TS files
        ts_files = [
            str(f.relative_to(project_root)).replace("\\", "/")
            for f in files
            if f.suffix in self.extensions
        ]
        if not ts_files:
            return {}

        # Detect workspace packages
        workspace_packages = _detect_workspace_packages(project_root)

        # Build stdin payload (new object format)
        stdin_payload = json.dumps({
            "files": ts_files,
            "workspacePackages": workspace_packages,
        })

        try:
            proc = subprocess.run(
                ["node", str(_TS_RUNNER)] + [str(tc) for tc in tsconfigs],
                cwd=str(project_root),
                input=stdin_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise FactsExtractionError("ts-morph extraction timed out (120s)")
        except FileNotFoundError:
            raise FactsExtractionError("node executable not found")

        # Surface ts-morph diagnostics (warnings, file counts) from stderr
        if proc.stderr:
            import logging
            logger = logging.getLogger(__name__)
            for line in proc.stderr.strip().splitlines():
                logger.info("[typescript] %s", line)

        if proc.returncode != 0:
            raise FactsExtractionError(
                f"ts-morph extraction failed (exit {proc.returncode}): {proc.stderr[:500]}"
            )

        try:
            raw = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise FactsExtractionError(f"Invalid JSON from ts-morph runner: {e}")

        result: dict[str, ExtractedFacts] = {}
        for rel_path, data in raw.items():
            result[rel_path] = ExtractedFacts(
                imports=data.get("imports", []),
                exports=data.get("exports", []),
                calls=data.get("calls", []),
                member_writes=data.get("member_writes", []),
            )
        return result

    @staticmethod
    def _find_tsconfig(project_root: Path) -> Path | None:
        """Walk up from project_root looking for tsconfig.json."""
        current = project_root.resolve()
        while True:
            candidate = current / "tsconfig.json"
            if candidate.is_file():
                return candidate
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None
