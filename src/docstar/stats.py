"""Token counting and statistics for shadow documentation."""

from dataclasses import dataclass
from pathlib import Path

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

from .config import Config
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


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken (cl100k_base).
    
    Falls back to character-based approximation if tiktoken unavailable.
    """
    if HAS_TIKTOKEN:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    else:
        # Rough approximation: ~4 chars per token for code
        return len(text) // 4


def count_file_tokens(path: Path) -> int:
    """Count tokens in a file."""
    try:
        content = path.read_text(encoding="utf-8")
        return count_tokens(content)
    except Exception:
        return 0


def gather_stats(config: Config) -> ProjectStats:
    """Gather token statistics for all files in the project."""
    files = discover_files(config)
    file_stats: list[FileStats] = []
    
    for source_path in files:
        shadow_path = config.shadow_path_for(source_path)
        
        source_tokens = count_file_tokens(source_path)
        shadow_exists = shadow_path.exists()
        shadow_tokens = count_file_tokens(shadow_path) if shadow_exists else 0
        
        file_stats.append(FileStats(
            source_path=source_path.relative_to(config.root_path),
            shadow_path=shadow_path.relative_to(config.root_path) if shadow_exists else shadow_path,
            source_tokens=source_tokens,
            shadow_tokens=shadow_tokens,
            source_exists=True,
            shadow_exists=shadow_exists,
        ))
    
    return ProjectStats(files=file_stats)


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
    
    if not HAS_TIKTOKEN:
        lines.append("")
        lines.append("⚠ Using character-based token estimation.")
        lines.append("  Install tiktoken for accurate counts: pip install tiktoken")
    
    # Per-file breakdown
    if verbose and stats.files:
        lines.append("")
        lines.append("-" * 60)
        lines.append("PER-FILE BREAKDOWN")
        lines.append("-" * 60)
        
        # Sort by source tokens descending
        sorted_files = sorted(stats.files, key=lambda f: f.source_tokens, reverse=True)
        
        for f in sorted_files:
            status = "✓" if f.shadow_exists else "✗"
            ratio_str = f"{f.compression_ratio:.0%}" if f.compression_ratio else "N/A"
            lines.append(
                f"  {status} {f.source_path}"
            )
            lines.append(
                f"      source: {f.source_tokens:,} → shadow: {f.shadow_tokens:,} ({ratio_str})"
            )
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)
