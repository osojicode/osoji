"""Token counting and statistics for shadow documentation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .llm import TokenCounter, estimate_tokens_offline
from .walker import discover_files


@dataclass
class FileStats:
    """Token statistics for a single file."""
    source_path: Path
    shadow_path: Path
    source_tokens: int
    shadow_tokens: int
    source_exists: bool = True
    shadow_exists: bool = True

    @property
    def compression_ratio(self) -> float | None:
        """Return shadow/source ratio. Lower is better compression."""
        if not self.shadow_exists or self.source_tokens == 0:
            return None
        return self.shadow_tokens / self.source_tokens

    @property
    def savings_percent(self) -> float | None:
        """Return percentage of tokens saved. Higher is better."""
        ratio = self.compression_ratio
        if ratio is None:
            return None
        return (1 - ratio) * 100


@dataclass
class ProjectStats:
    """Aggregate token statistics for a project."""
    files: list[FileStats]
    used_api: bool = True  # Whether Anthropic API was used for counting

    @property
    def total_source_tokens(self) -> int:
        return sum(f.source_tokens for f in self.files if f.source_exists)

    @property
    def total_shadow_tokens(self) -> int:
        return sum(f.shadow_tokens for f in self.files if f.shadow_exists)

    @property
    def files_with_shadow(self) -> int:
        return sum(1 for f in self.files if f.shadow_exists)

    @property
    def compression_ratio(self) -> float | None:
        if self.total_source_tokens == 0:
            return None
        return self.total_shadow_tokens / self.total_source_tokens

    @property
    def savings_percent(self) -> float | None:
        ratio = self.compression_ratio
        if ratio is None:
            return None
        return (1 - ratio) * 100


async def count_tokens_async(text: str, counter: TokenCounter) -> int:
    """Count tokens using Anthropic API.

    Args:
        text: Text to count tokens for
        counter: TokenCounter instance

    Returns:
        Token count
    """
    return await counter.count_text_async(text)


def count_tokens(text: str) -> int:
    """Count tokens using Anthropic API (sync wrapper).

    Creates a new TokenCounter for each call. For batch operations,
    use gather_stats_async() instead.

    Args:
        text: Text to count tokens for

    Returns:
        Token count
    """
    async def _count():
        counter = TokenCounter()
        try:
            return await counter.count_text_async(text)
        finally:
            await counter.close()
    return asyncio.run(_count())


def count_tokens_offline(text: str) -> int:
    """Count tokens using offline estimation (character-based).

    Use when API access is not available or for quick estimates.

    Args:
        text: Text to count tokens for

    Returns:
        Estimated token count
    """
    return estimate_tokens_offline(text)


async def count_file_tokens_async(path: Path, counter: TokenCounter) -> int:
    """Count tokens in a file using Anthropic API.

    Args:
        path: Path to the file
        counter: TokenCounter instance

    Returns:
        Token count, or 0 if file can't be read
    """
    try:
        content = path.read_text(encoding="utf-8")
        return await counter.count_text_async(content)
    except Exception:
        return 0


def count_file_tokens(path: Path) -> int:
    """Count tokens in a file (sync wrapper)."""
    try:
        content = path.read_text(encoding="utf-8")
        return count_tokens(content)
    except Exception:
        return 0


async def gather_stats_async(config: Config, use_api: bool = True) -> ProjectStats:
    """Gather token statistics for all files in the project asynchronously.

    Args:
        config: Project configuration
        use_api: If True, use Anthropic API for accurate counts.
                 If False, use offline estimation.

    Returns:
        ProjectStats with token counts for all files
    """
    files = discover_files(config)
    file_stats: list[FileStats] = []

    if use_api:
        counter = TokenCounter()
        try:
            # Count tokens for all files concurrently
            tasks = []
            for source_path in files:
                shadow_path = config.shadow_path_for(source_path)
                shadow_exists = shadow_path.exists()
                tasks.append(_gather_file_stats_async(
                    config, source_path, shadow_path, shadow_exists, counter
                ))
            file_stats = await asyncio.gather(*tasks)
        finally:
            await counter.close()
    else:
        # Offline mode - use character-based estimation
        for source_path in files:
            shadow_path = config.shadow_path_for(source_path)
            shadow_exists = shadow_path.exists()

            try:
                source_content = source_path.read_text(encoding="utf-8")
                source_tokens = estimate_tokens_offline(source_content)
            except Exception:
                source_tokens = 0

            if shadow_exists:
                try:
                    shadow_content = shadow_path.read_text(encoding="utf-8")
                    shadow_tokens = estimate_tokens_offline(shadow_content)
                except Exception:
                    shadow_tokens = 0
            else:
                shadow_tokens = 0

            file_stats.append(FileStats(
                source_path=source_path.relative_to(config.root_path),
                shadow_path=shadow_path.relative_to(config.root_path) if shadow_exists else shadow_path,
                source_tokens=source_tokens,
                shadow_tokens=shadow_tokens,
                source_exists=True,
                shadow_exists=shadow_exists,
            ))

    return ProjectStats(files=file_stats, used_api=use_api)


async def _gather_file_stats_async(
    config: Config,
    source_path: Path,
    shadow_path: Path,
    shadow_exists: bool,
    counter: TokenCounter,
) -> FileStats:
    """Gather stats for a single file asynchronously."""
    try:
        source_content = source_path.read_text(encoding="utf-8")
        source_tokens = await counter.count_text_async(source_content)
    except Exception:
        source_tokens = 0

    if shadow_exists:
        try:
            shadow_content = shadow_path.read_text(encoding="utf-8")
            shadow_tokens = await counter.count_text_async(shadow_content)
        except Exception:
            shadow_tokens = 0
    else:
        shadow_tokens = 0

    return FileStats(
        source_path=source_path.relative_to(config.root_path),
        shadow_path=shadow_path.relative_to(config.root_path) if shadow_exists else shadow_path,
        source_tokens=source_tokens,
        shadow_tokens=shadow_tokens,
        source_exists=True,
        shadow_exists=shadow_exists,
    )


def gather_stats(config: Config) -> ProjectStats:
    """Gather token statistics for all files in the project (sync wrapper).

    Uses Anthropic API for accurate token counts.

    Args:
        config: Project configuration

    Returns:
        ProjectStats with token counts for all files
    """
    return asyncio.run(gather_stats_async(config, use_api=True))


def gather_stats_offline(config: Config) -> ProjectStats:
    """Gather token statistics using offline estimation.

    Use when API access is not available.

    Args:
        config: Project configuration

    Returns:
        ProjectStats with estimated token counts
    """
    return asyncio.run(gather_stats_async(config, use_api=False))


def format_stats_report(stats: ProjectStats, verbose: bool = False) -> str:
    """Format statistics as a human-readable report."""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("DOCSTAR TOKEN STATISTICS")
    lines.append("=" * 60)
    lines.append("")

    # Summary
    lines.append(f"Files analyzed:      {len(stats.files)}")
    lines.append(f"Files with shadows:  {stats.files_with_shadow}")
    lines.append("")
    lines.append(f"Source tokens:       {stats.total_source_tokens:,}")
    lines.append(f"Shadow tokens:       {stats.total_shadow_tokens:,}")
    lines.append("")

    if stats.compression_ratio is not None:
        lines.append(f"Compression ratio:   {stats.compression_ratio:.2%}")
        lines.append(f"Token savings:       {stats.savings_percent:.1f}%")
    else:
        lines.append("Compression ratio:   N/A (no shadow docs)")

    # Per-file breakdown
    if verbose and stats.files:
        lines.append("")
        lines.append("-" * 60)
        lines.append("PER-FILE BREAKDOWN")
        lines.append("-" * 60)

        # Sort by source tokens descending
        sorted_files = sorted(stats.files, key=lambda f: f.source_tokens, reverse=True)

        for f in sorted_files:
            status = "+" if f.shadow_exists else "-"
            ratio_str = f"{f.compression_ratio:.0%}" if f.compression_ratio else "N/A"
            lines.append(
                f"  {status} {f.source_path}"
            )
            lines.append(
                f"      source: {f.source_tokens:,} -> shadow: {f.shadow_tokens:,} ({ratio_str})"
            )

    lines.append("")
    lines.append("-" * 60)
    if stats.used_api:
        lines.append("Token counts via Anthropic API")
    else:
        lines.append("Token counts via offline estimation (~4 chars/token)")
    lines.append("=" * 60)

    return "\n".join(lines)
