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

from .config import Config
from .llm.base import LLMProvider
from .llm.factory import create_provider
from .llm.logging import LoggingProvider
from .rate_limiter import RateLimiter, get_config_with_overrides


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
    metadata: dict[str, Any] = field(default_factory=dict)


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
        rate_limiter: RateLimiter,
        config: Config,
        on_progress: Callable | None = None,
    ) -> JunkAnalysisResult:
        """Run analysis asynchronously.

        Args:
            provider: LLM provider for API calls
            rate_limiter: Rate limiter for API throttling
            config: Docstar configuration
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
        symbols_dir = config.root_path / ".docstar" / "symbols"
        if not symbols_dir.exists():
            print(f"  [skip] No symbols data found. Run 'docstar shadow .' first.", flush=True)
            return JunkAnalysisResult(findings=[], total_candidates=0, analyzer_name=self.name)

        async def _run() -> JunkAnalysisResult:
            provider = create_provider("anthropic")
            logging_provider = LoggingProvider(provider)
            rl = rate_limiter if rate_limiter is not None else RateLimiter(get_config_with_overrides("anthropic"))
            try:
                return await self.analyze_async(
                    logging_provider, rl, config, on_progress
                )
            finally:
                await logging_provider.close()

        return asyncio.run(_run())


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
