"""TypeScript language plugin — extraction via ts-morph (Node.js subprocess)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .base import ExtractedFacts, FactsExtractionError, LanguagePlugin, PluginUnavailableError

logger = logging.getLogger(__name__)

_TS_RUNNER = Path(__file__).parent / "ts_runner" / "extract.js"


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
        try:
            subprocess.run(
                ["node", "-e", "require('ts-morph')"],
                cwd=str(project_root),
                capture_output=True,
                timeout=10,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            raise PluginUnavailableError(
                "ts-morph not found",
                "Run: npm install --save-dev ts-morph",
            )

    def extract_project_facts(
        self, project_root: Path, files: list[Path]
    ) -> dict[str, ExtractedFacts]:
        self.check_available(project_root)

        # Find tsconfig.json by walking up from project_root
        tsconfig = self._find_tsconfig(project_root)
        if not tsconfig:
            raise FactsExtractionError(
                f"No tsconfig.json found at or above {project_root}"
            )

        # Filter to TS files
        ts_files = [
            str(f.relative_to(project_root)).replace("\\", "/")
            for f in files
            if f.suffix in self.extensions
        ]
        if not ts_files:
            return {}

        try:
            proc = subprocess.run(
                ["node", str(_TS_RUNNER), str(tsconfig)],
                cwd=str(project_root),
                input=json.dumps(ts_files),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise FactsExtractionError("ts-morph extraction timed out (120s)")
        except FileNotFoundError:
            raise FactsExtractionError("node executable not found")

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
