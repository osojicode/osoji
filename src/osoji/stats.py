"""Token counting and statistics for shadow documentation."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .hasher import compute_hash
from .llm import TokenCounter, estimate_tokens_offline
from .walker import discover_files

logger = logging.getLogger(__name__)


@dataclass
class FileStats:
    """Token statistics for a single file."""
    source_path: Path
    shadow_path: Path
    source_tokens: int
    shadow_tokens: int
    shadow_exists: bool = True

    @property
    def compression_ratio(self) -> float | None:
        """Return shadow/source ratio. Lower is better compression."""
        if not self.shadow_exists or self.source_tokens == 0:
            return None
        return self.shadow_tokens / self.source_tokens



@dataclass
class ProjectStats:
    """Aggregate token statistics for a project."""
    files: list[FileStats]
    used_api: bool = True  # Whether Anthropic API was used for counting

    @property
    def total_source_tokens(self) -> int:
        return sum(f.source_tokens for f in self.files)

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



def _load_token_cache(config: Config) -> dict:
    """Load the persistent token-count cache from disk.

    Returns an empty dict if the file is missing or corrupt.
    """
    try:
        return json.loads(config.token_cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_token_cache(config: Config, cache: dict) -> None:
    """Write the token-count cache to disk."""
    try:
        config.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        config.token_cache_path.write_text(
            json.dumps(cache, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        logger.warning("Failed to write token cache to %s", config.token_cache_path)


async def _gather_file_stats_cached(
    config: Config,
    source_path: Path,
    shadow_path: Path,
    shadow_exists: bool,
    counter: TokenCounter,
    token_cache: dict,
) -> FileStats:
    """Gather stats for a single file, using the persistent hash cache."""
    rel_key = str(source_path.relative_to(config.root_path))
    entry = token_cache.get(rel_key, {})

    # Read source content once (needed for hash and possibly API)
    try:
        source_content = source_path.read_text(encoding="utf-8")
    except Exception:
        source_content = ""
    source_hash = compute_hash(source_content) if source_content else ""

    # Read shadow content once
    shadow_content = ""
    if shadow_exists:
        try:
            shadow_content = shadow_path.read_text(encoding="utf-8")
        except Exception:
            pass
    shadow_hash = compute_hash(shadow_content) if shadow_content else ""

    # Check source cache hit
    if source_content and entry.get("source_hash") == source_hash:
        source_tokens = entry["source_tokens"]
    elif source_content:
        source_tokens = await counter.count_text_async(source_content)
    else:
        source_tokens = 0

    # Check shadow cache hit
    if shadow_exists and shadow_content and entry.get("shadow_hash") == shadow_hash:
        shadow_tokens = entry["shadow_tokens"]
    elif shadow_exists and shadow_content:
        shadow_tokens = await counter.count_text_async(shadow_content)
    else:
        shadow_tokens = 0

    # Update cache entry
    token_cache[rel_key] = {
        "source_hash": source_hash,
        "source_tokens": source_tokens,
        "shadow_hash": shadow_hash,
        "shadow_tokens": shadow_tokens,
    }

    return FileStats(
        source_path=source_path.relative_to(config.root_path),
        shadow_path=shadow_path.relative_to(config.root_path),
        source_tokens=source_tokens,
        shadow_tokens=shadow_tokens,
        shadow_exists=shadow_exists,
    )


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
        token_cache = _load_token_cache(config)
        counter = TokenCounter()
        try:
            # Count tokens for all files concurrently, with hash cache
            tasks = []
            for source_path in files:
                shadow_path = config.shadow_path_for(source_path)
                shadow_exists = shadow_path.exists()
                tasks.append(_gather_file_stats_cached(
                    config, source_path, shadow_path, shadow_exists,
                    counter, token_cache,
                ))
            file_stats = await asyncio.gather(*tasks)
        finally:
            await counter.close()
        # Prune stale entries: only keep files we just processed
        processed_keys = {str(p.relative_to(config.root_path)) for p in files}
        token_cache = {k: v for k, v in token_cache.items() if k in processed_keys}
        _save_token_cache(config, token_cache)
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
                shadow_path=shadow_path.relative_to(config.root_path),
                source_tokens=source_tokens,
                shadow_tokens=shadow_tokens,
                shadow_exists=shadow_exists,
            ))

    return ProjectStats(files=file_stats, used_api=use_api)


def gather_stats(config: Config) -> ProjectStats:
    """Gather token statistics for all files in the project (sync wrapper).

    Uses Anthropic API for accurate token counts.

    Args:
        config: Project configuration

    Returns:
        ProjectStats with token counts for all files
    """
    return asyncio.run(gather_stats_async(config, use_api=True))


def format_stats_report(stats: ProjectStats, verbose: bool = False) -> str:
    """Format statistics as a human-readable report."""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("OSOJI TOKEN STATISTICS")
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
            ratio = f.compression_ratio
            ratio_str = f"{ratio:.0%}" if ratio is not None else "N/A"
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
