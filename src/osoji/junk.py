"""Unified junk code analysis framework.

Provides a common ABC and shared types for all junk detection analyzers
(dead code, dead plumbing, and future categories). Each analyzer follows
a two-phase pattern: cheap Python candidate filter -> LLM verification.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Config, SHADOW_DIR
from .llm.base import LLMProvider
from .llm.runtime import create_runtime
from .rate_limiter import RateLimiter


@dataclass
class JunkFinding:
    """A single confirmed junk item found by an analyzer."""

    source_path: str
    name: str                 # item identifier
    kind: str                 # function, class, config_field, etc.
    category: str             # dead_symbol, unactuated_config, etc.
    line_start: int
    line_end: int | None
    confidence: float         # 0.0-1.0
    reason: str
    remediation: str
    original_purpose: str     # what the item was for
    confidence_source: str = "llm_inferred"  # "ast_proven" | "llm_inferred" | "heuristic"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.line_end is not None and self.line_end < self.line_start:
            raise ValueError(
                f"line_end ({self.line_end}) must be >= line_start ({self.line_start}) "
                f"for {self.name!r} in {self.source_path}"
            )


@dataclass
class JunkAnalysisResult:
    """Result from a single junk analyzer run."""

    findings: list[JunkFinding]       # confirmed junk only
    total_candidates: int             # how many items were examined
    analyzer_name: str


class JunkAnalyzer(ABC):
    """Abstract base class for junk code analyzers.

    Each analyzer detects a specific category of unused/dead content
    in the repository.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this analyzer (e.g. 'dead_code')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description (e.g. 'Detect cross-file dead code')."""
        ...

    @property
    @abstractmethod
    def cli_flag(self) -> str:
        """CLI flag name without -- prefix (e.g. 'dead-code')."""
        ...

    @abstractmethod
    async def analyze_async(
        self,
        provider: LLMProvider,
        config: Config,
        on_progress: Callable | None = None,
    ) -> JunkAnalysisResult:
        """Run analysis asynchronously.

        Args:
            provider: LLM provider for API calls
            config: Osoji configuration
            on_progress: Optional callback (completed, total, path, status)

        Returns:
            JunkAnalysisResult with confirmed findings.
        """
        ...

    def analyze(
        self,
        config: Config,
        on_progress: Callable | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> JunkAnalysisResult:
        """Sync wrapper for analyze_async.

        Creates provider and rate limiter internally (unless provided),
        runs async analysis, then cleans up.
        """
        symbols_dir = config.root_path / SHADOW_DIR / "symbols"
        if not symbols_dir.exists():
            print(f"  [skip] No symbols data found. Run 'osoji shadow .' first.", flush=True)
            return JunkAnalysisResult(findings=[], total_candidates=0, analyzer_name=self.name)

        async def _run() -> JunkAnalysisResult:
            logging_provider, _ = create_runtime(config, rate_limiter=rate_limiter)
            try:
                return await self.analyze_async(
                    logging_provider, config, on_progress
                )
            finally:
                await logging_provider.close()

        return asyncio.run(_run())


def validate_line_ranges(tool_name: str, tool_input: dict) -> list[str]:
    """Tool input validator: ensure line_end >= line_start in findings/items arrays.

    Usable as a ``tool_input_validators`` entry on ``CompletionOptions``.
    """
    errors: list[str] = []
    for key in ("findings", "items", "obligations"):
        items = tool_input.get(key, [])
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            ls = item.get("line_start")
            le = item.get("line_end")
            if ls is not None and le is not None and le < ls:
                errors.append(
                    f"{key}[{i}]: line_end ({le}) must be >= line_start ({ls})"
                )
    return errors


def load_shadow_content(config: Config, relative_path: str) -> str:
    """Load shadow doc content for a relative source path.

    Shared utility used by dead code, dead plumbing, and other analyzers.
    """
    shadow_path = config.shadow_root / (relative_path + ".shadow.md")
    if shadow_path.exists():
        try:
            return shadow_path.read_text(encoding="utf-8")
        except OSError:
            pass
    return ""
