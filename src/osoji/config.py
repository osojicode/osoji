"""Configuration for Osoji."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib
from typing import Any, Literal


# Shadow doc output directory name
SHADOW_DIR = ".osoji"

# Directories to ignore during traversal
DEFAULT_IGNORE_PATTERNS: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "build",
    "dist",
    SHADOW_DIR,
    ".idea",
    ".vscode",
    ".github",
    # Build output
    "target",
    # Cargo / Rust ecosystem
    ".cargo",
    "toolchains",
    "registry",
    # Vendored dependencies (Go, PHP, Ruby)
    "vendor",
    # Rustup home
    ".rustup",
    # Gradle cache
    ".gradle",
    # Next.js / Nuxt.js / Turborepo / Parcel
    ".next",
    ".nuxt",
    ".turbo",
    ".parcel-cache",
    # Generic caches / temp / logs
    ".cache",
    "tmp",
    "temp",
    "logs",
    # Test coverage
    "coverage",
    ".nyc_output",
    # Legacy package managers
    "bower_components",
    # Lock files (large, machine-generated)
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
    "Gemfile.lock",
}

# Documentation file detection settings
DOC_EXTENSIONS: set[str] = {".md", ".markdown", ".rst", ".txt"}
DOC_FILENAMES: set[str] = {"README", "CHANGELOG", "CONTRIBUTING", "LICENSE", "AUTHORS"}
DOC_DIRECTORIES: set[str] = {"docs", "documentation", "doc"}

# File extensions to process
DEFAULT_EXTENSIONS: set[str] = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".clj",
    ".ex",
    ".exs",
    ".erl",
    ".hs",
    ".ml",
    ".mli",
    ".lua",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".r",
    ".R",
    ".sql",
    ".vue",
    ".svelte",
    # Metadata / config files
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".cfg",
    ".ini",
}

SHADOW_SUBDIR = "shadow"
DIRECTORY_SHADOW_FILENAME = "_directory.shadow.md"

DEFAULT_PROVIDER = "anthropic"
ENV_PROVIDER = "OSOJI_PROVIDER"
ENV_MODEL = "OSOJI_MODEL"
ENV_MODEL_SMALL = "OSOJI_MODEL_SMALL"
ENV_MODEL_MEDIUM = "OSOJI_MODEL_MEDIUM"
ENV_MODEL_LARGE = "OSOJI_MODEL_LARGE"

GLOBAL_CONFIG_FILENAME = "config.toml"
LOCAL_CONFIG_FILENAME = ".osoji.local.toml"

ANTHROPIC_MODEL_SMALL = "claude-haiku-4-5-20251001"
ANTHROPIC_MODEL_MEDIUM = "claude-sonnet-4-6"
ANTHROPIC_MODEL_LARGE = "claude-opus-4-6"

OPENAI_MODEL_SMALL = "gpt-5-mini"
OPENAI_MODEL_MEDIUM = "gpt-5.2"
OPENAI_MODEL_LARGE = "gpt-5.4"

BUILTIN_PROVIDER_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {
        "small": ANTHROPIC_MODEL_SMALL,
        "medium": ANTHROPIC_MODEL_MEDIUM,
        "large": ANTHROPIC_MODEL_LARGE,
    },
    "openai": {
        "small": OPENAI_MODEL_SMALL,
        "medium": OPENAI_MODEL_MEDIUM,
        "large": OPENAI_MODEL_LARGE,
    },
}

# Backward-compatible aliases retained for callers/tests that still import them.
MODEL_SMALL = ANTHROPIC_MODEL_SMALL
MODEL_MEDIUM = ANTHROPIC_MODEL_MEDIUM
MODEL_LARGE = ANTHROPIC_MODEL_LARGE
DEFAULT_MODEL = MODEL_MEDIUM

ModelTier = Literal["small", "medium", "large"]
ResolutionSource = Literal["cli", "env", "project", "global", "builtin"]
RESOLUTION_ORDER: tuple[ResolutionSource, ...] = (
    "cli",
    "env",
    "project",
    "global",
    "builtin",
)


def get_global_config_path() -> Path:
    """Return the user-level Osoji config path."""

    return Path.home() / ".config" / "osoji" / GLOBAL_CONFIG_FILENAME


def _read_env(name: str) -> str | None:
    """Read an environment variable, treating empty strings as unset."""

    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _read_optional_str(value: Any, *, context: str) -> str | None:
    """Validate a config scalar and return a stripped string or None."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"{context} must be a string.")
    stripped = value.strip()
    return stripped or None


def _normalize_provider(value: str, *, context: str) -> str:
    """Normalize and validate a provider name."""

    from .llm.registry import normalize_provider_name

    try:
        return normalize_provider_name(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid provider in {context}: {value}") from exc


@dataclass(frozen=True)
class ProviderPolicyConfig:
    """Provider-specific model policy loaded from TOML."""

    model: str | None = None
    small: str | None = None
    medium: str | None = None
    large: str | None = None

    def value_for(self, tier: ModelTier) -> tuple[str | None, str | None]:
        """Return the best candidate value plus its TOML key suffix."""

        tier_value = getattr(self, tier)
        if tier_value:
            return tier_value, tier
        if self.model:
            return self.model, "model"
        return None, None


@dataclass(frozen=True)
class PolicyFileConfig:
    """Resolved contents of a TOML model policy file."""

    path: Path
    default_provider: str | None = None
    providers: dict[str, ProviderPolicyConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolutionTraceEntry:
    """One candidate value considered during resolution."""

    source: ResolutionSource
    value: str | None
    key: str | None = None
    path: str | None = None
    selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source": self.source,
            "value": self.value,
            "selected": self.selected,
        }
        if self.key is not None:
            data["key"] = self.key
        if self.path is not None:
            data["path"] = self.path
        return data


@dataclass(frozen=True)
class ResolvedSetting:
    """Final resolved value plus full precedence trace."""

    value: str
    source: ResolutionSource
    key: str | None
    path: str | None
    trace: tuple[ResolutionTraceEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "value": self.value,
            "source": self.source,
            "trace": [entry.to_dict() for entry in self.trace],
        }
        if self.key is not None:
            data["key"] = self.key
        if self.path is not None:
            data["path"] = self.path
        return data


@dataclass(frozen=True)
class ResolvedModelPolicy:
    """Resolved provider and tier mapping for a config instance."""

    provider: ResolvedSetting
    models: dict[ModelTier, ResolvedSetting]
    resolution_order: tuple[ResolutionSource, ...] = RESOLUTION_ORDER

    def model_for(self, tier: ModelTier) -> str:
        """Return the resolved model for a tier."""

        return self.models[tier].value

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolution_order": list(self.resolution_order),
            "provider": self.provider.to_dict(),
            "models": {
                tier: self.models[tier].to_dict()
                for tier in ("small", "medium", "large")
            },
        }


def _load_policy_file(path: Path) -> PolicyFileConfig | None:
    """Load a TOML policy file if present."""

    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Invalid Osoji config file {path}: {exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"Failed to read Osoji config file {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Osoji config file {path} must contain a TOML table.")

    default_provider_raw = _read_optional_str(
        data.get("default_provider"),
        context=f"{path}: default_provider",
    )
    default_provider = (
        _normalize_provider(default_provider_raw, context=f"{path}: default_provider")
        if default_provider_raw
        else None
    )

    providers_raw = data.get("providers")
    if providers_raw is None:
        providers_raw = {}
    if not isinstance(providers_raw, dict):
        raise RuntimeError(f"{path}: providers must be a TOML table.")

    providers: dict[str, ProviderPolicyConfig] = {}
    for provider_name, provider_data in providers_raw.items():
        if not isinstance(provider_data, dict):
            raise RuntimeError(f"{path}: providers.{provider_name} must be a TOML table.")
        normalized_provider = _normalize_provider(
            str(provider_name),
            context=f"{path}: providers.{provider_name}",
        )
        providers[normalized_provider] = ProviderPolicyConfig(
            model=_read_optional_str(
                provider_data.get("model"),
                context=f"{path}: providers.{provider_name}.model",
            ),
            small=_read_optional_str(
                provider_data.get("small"),
                context=f"{path}: providers.{provider_name}.small",
            ),
            medium=_read_optional_str(
                provider_data.get("medium"),
                context=f"{path}: providers.{provider_name}.medium",
            ),
            large=_read_optional_str(
                provider_data.get("large"),
                context=f"{path}: providers.{provider_name}.large",
            ),
        )

    return PolicyFileConfig(path=path, default_provider=default_provider, providers=providers)


@dataclass(frozen=True)
class _Candidate:
    """Intermediate candidate before final setting selection."""

    source: ResolutionSource
    value: str | None
    key: str | None = None
    path: str | None = None


def _resolve_setting(candidates: list[_Candidate], *, error_message: str | None = None) -> ResolvedSetting:
    """Select the first non-empty candidate and build a trace."""

    selected = next((candidate for candidate in candidates if candidate.value is not None), None)
    if selected is None:
        if error_message is None:
            raise RuntimeError("No setting candidates were available.")
        raise RuntimeError(error_message)
    trace = tuple(
        ResolutionTraceEntry(
            source=candidate.source,
            value=candidate.value,
            key=candidate.key,
            path=candidate.path,
            selected=(candidate is selected),
        )
        for candidate in candidates
    )
    return ResolvedSetting(
        value=selected.value,
        source=selected.source,
        key=selected.key,
        path=selected.path,
        trace=trace,
    )


def _builtin_model_candidate(provider: str, tier: ModelTier) -> _Candidate:
    """Return the built-in provider/tier candidate if available."""

    provider_models = BUILTIN_PROVIDER_MODELS.get(provider)
    if not provider_models:
        return _Candidate(source="builtin", value=None, key=None, path=None)
    return _Candidate(
        source="builtin",
        value=provider_models[tier],
        key=f"builtin.{provider}.{tier}",
        path=None,
    )


def _file_model_candidate(
    source: ResolutionSource,
    provider: str,
    tier: ModelTier,
    policy: PolicyFileConfig | None,
) -> _Candidate:
    """Resolve a provider-specific model candidate from a TOML source."""

    if policy is None:
        return _Candidate(source=source, value=None, key=None, path=None)
    provider_policy = policy.providers.get(provider)
    if provider_policy is None:
        return _Candidate(source=source, value=None, key=None, path=str(policy.path))
    value, key_suffix = provider_policy.value_for(tier)
    key = None
    if key_suffix is not None:
        key = f"providers.{provider}.{key_suffix}"
    return _Candidate(source=source, value=value, key=key, path=str(policy.path))


def _resolve_model_policy(
    *,
    cli_provider: str | None,
    cli_model: str | None,
    env_provider: str | None,
    env_model: str | None,
    env_small: str | None,
    env_medium: str | None,
    env_large: str | None,
    project_policy: PolicyFileConfig | None,
    global_policy: PolicyFileConfig | None,
) -> ResolvedModelPolicy:
    """Resolve provider and tier mappings across all sources."""

    provider_candidates = [
        _Candidate(
            source="cli",
            value=(_normalize_provider(cli_provider, context="CLI --provider") if cli_provider else None),
            key="--provider" if cli_provider else None,
            path=None,
        ),
        _Candidate(
            source="env",
            value=(_normalize_provider(env_provider, context=ENV_PROVIDER) if env_provider else None),
            key=ENV_PROVIDER if env_provider else None,
            path=None,
        ),
        _Candidate(
            source="project",
            value=project_policy.default_provider if project_policy else None,
            key="default_provider" if project_policy and project_policy.default_provider else None,
            path=str(project_policy.path) if project_policy else None,
        ),
        _Candidate(
            source="global",
            value=global_policy.default_provider if global_policy else None,
            key="default_provider" if global_policy and global_policy.default_provider else None,
            path=str(global_policy.path) if global_policy else None,
        ),
        _Candidate(
            source="builtin",
            value=DEFAULT_PROVIDER,
            key="default_provider",
            path=None,
        ),
    ]
    resolved_provider = _resolve_setting(provider_candidates)
    provider = resolved_provider.value

    env_tier_values = {
        "small": env_small,
        "medium": env_medium,
        "large": env_large,
    }
    env_tier_keys = {
        "small": ENV_MODEL_SMALL,
        "medium": ENV_MODEL_MEDIUM,
        "large": ENV_MODEL_LARGE,
    }

    models: dict[ModelTier, ResolvedSetting] = {}
    for tier in ("small", "medium", "large"):
        env_value = env_tier_values[tier]
        env_key = env_tier_keys[tier] if env_value else (ENV_MODEL if env_model else None)
        env_resolved_value = env_value or env_model
        candidates = [
            _Candidate(
                source="cli",
                value=cli_model,
                key="--model" if cli_model else None,
                path=None,
            ),
            _Candidate(
                source="env",
                value=env_resolved_value,
                key=env_key,
                path=None,
            ),
            _file_model_candidate("project", provider, tier, project_policy),
            _file_model_candidate("global", provider, tier, global_policy),
            _builtin_model_candidate(provider, tier),
        ]
        error_message = (
            f"No model configured for provider '{provider}'. "
            f"Set --model, {ENV_MODEL}, or {env_tier_keys[tier]}."
        )
        models[tier] = _resolve_setting(candidates, error_message=error_message)

    return ResolvedModelPolicy(provider=resolved_provider, models=models)


def format_policy_trace(snapshot: dict[str, Any]) -> str:
    """Format a serialized policy snapshot for human inspection."""

    lines = ["Osoji config resolution"]
    order = snapshot.get("resolution_order") or list(RESOLUTION_ORDER)
    lines.append(f"  order: {' > '.join(order)}")
    lines.append("")

    def render_setting(label: str, payload: dict[str, Any]) -> None:
        lines.append(
            f"  {label}: {payload['value']} [{payload['source']}]"
        )
        for trace in payload.get("trace", []):
            source = trace["source"]
            value = trace.get("value")
            key = trace.get("key")
            path = trace.get("path")
            selected = trace.get("selected", False)
            value_text = value if value is not None else "unset"
            origin_parts = []
            if key:
                origin_parts.append(key)
            if path:
                origin_parts.append(path)
            origin = f" ({' @ '.join(origin_parts)})" if origin_parts else ""
            marker = " [selected]" if selected else ""
            lines.append(f"    - {source}: {value_text}{origin}{marker}")
        lines.append("")

    render_setting("provider", snapshot["provider"])
    for tier in ("small", "medium", "large"):
        render_setting(tier, snapshot["models"][tier])
    return "\n".join(lines).rstrip()


@dataclass
class Config:
    """Configuration for Osoji commands and model policy resolution."""

    root_path: Path
    ignore_patterns: set[str] = field(default_factory=lambda: DEFAULT_IGNORE_PATTERNS.copy())
    extensions: set[str] = field(default_factory=lambda: DEFAULT_EXTENSIONS.copy())
    provider: str | None = None
    model: str | None = None
    model_small: str | None = None
    model_medium: str | None = None
    model_large: str | None = None
    force: bool = False
    respect_gitignore: bool = True
    verbose: bool = False
    quiet: bool = False

    # Documentation detection (for debris scanning)
    doc_extensions: set[str] = field(default_factory=lambda: DOC_EXTENSIONS.copy())
    doc_filenames: set[str] = field(default_factory=lambda: DOC_FILENAMES.copy())
    doc_directories: set[str] = field(default_factory=lambda: DOC_DIRECTORIES.copy())

    _project_policy: PolicyFileConfig | None = field(init=False, repr=False, default=None)
    _global_policy: PolicyFileConfig | None = field(init=False, repr=False, default=None)
    _resolved_policy: ResolvedModelPolicy = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.root_path = self.root_path.resolve()
        self.provider = _read_optional_str(self.provider, context="provider")
        self.model = _read_optional_str(self.model, context="model")
        self.model_small = _read_optional_str(self.model_small, context="model_small")
        self.model_medium = _read_optional_str(self.model_medium, context="model_medium")
        self.model_large = _read_optional_str(self.model_large, context="model_large")

        self._project_policy = _load_policy_file(self.project_config_path)
        self._global_policy = _load_policy_file(get_global_config_path())
        self._resolved_policy = _resolve_model_policy(
            cli_provider=self.provider,
            cli_model=self.model,
            env_provider=_read_env(ENV_PROVIDER),
            env_model=_read_env(ENV_MODEL),
            env_small=self.model_small or _read_env(ENV_MODEL_SMALL),
            env_medium=self.model_medium or _read_env(ENV_MODEL_MEDIUM),
            env_large=self.model_large or _read_env(ENV_MODEL_LARGE),
            project_policy=self._project_policy,
            global_policy=self._global_policy,
        )
        self.provider = self._resolved_policy.provider.value

    @property
    def project_config_path(self) -> Path:
        """Return the project-local policy path."""

        return self.root_path / LOCAL_CONFIG_FILENAME

    @property
    def global_config_path(self) -> Path:
        """Return the global policy path."""

        return get_global_config_path()

    @property
    def resolved_policy(self) -> ResolvedModelPolicy:
        """Return the fully resolved model policy."""

        return self._resolved_policy

    @property
    def config_snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of policy resolution."""

        return self._resolved_policy.to_dict()

    def model_for(self, tier: ModelTier = "medium") -> str:
        """Resolve the model ID to use for the requested tier."""

        return self._resolved_policy.model_for(tier)

    def format_resolution_banner(self) -> str:
        """Return a human-readable summary of config resolution."""

        return format_policy_trace(self.config_snapshot)

    def _to_relative(self, path: Path) -> Path:
        """Normalize a path to project-relative, accepting both absolute and relative."""

        return path.relative_to(self.root_path) if path.is_absolute() else path

    @property
    def shadow_root(self) -> Path:
        """Return the root directory for shadow docs."""

        return self.root_path / SHADOW_DIR / SHADOW_SUBDIR

    @property
    def logs_root(self) -> Path:
        """Return the root directory for Osoji log files."""

        return self.root_path / SHADOW_DIR / "logs"

    @property
    def llm_interactions_log_path(self) -> Path:
        """Return the JSONL transcript path for model interactions."""

        return self.logs_root / "llm-interactions.jsonl"

    @property
    def token_cache_path(self) -> Path:
        """Return the path to the persistent token-count cache."""

        return self.root_path / SHADOW_DIR / "token-cache.json"

    def shadow_path_for(self, source_path: Path) -> Path:
        """Return the shadow doc path for a given source file."""

        relative = self._to_relative(source_path)
        return self.shadow_root / (str(relative) + ".shadow.md")

    def findings_path_for(self, source_path: Path) -> Path:
        """Return the findings JSON path for a given source file."""

        relative = self._to_relative(source_path)
        return self.root_path / SHADOW_DIR / "findings" / (str(relative) + ".findings.json")

    def symbols_path_for(self, source_path: Path) -> Path:
        """Return the symbols JSON sidecar path for a given source file."""

        relative = self._to_relative(source_path)
        return self.root_path / SHADOW_DIR / "symbols" / (str(relative) + ".symbols.json")

    def facts_path_for(self, source_path: Path) -> Path:
        """Return the facts JSON path for a given source file."""

        relative = self._to_relative(source_path)
        return self.root_path / SHADOW_DIR / "facts" / (str(relative) + ".facts.json")

    def shadow_path_for_dir(self, dir_path: Path) -> Path:
        """Return the shadow doc path for a directory roll-up."""

        relative = self._to_relative(dir_path)
        if relative == Path("."):
            return self.shadow_root / "_root.shadow.md"
        return self.shadow_root / relative / DIRECTORY_SHADOW_FILENAME

    @property
    def analysis_root(self) -> Path:
        """Return the root directory for analysis outputs."""

        return self.root_path / SHADOW_DIR / "analysis"

    def analysis_docs_path_for(self, doc_path: Path) -> Path:
        """Return the analysis JSON path for a given doc file."""

        relative = self._to_relative(doc_path)
        return self.analysis_root / "docs" / (str(relative) + ".analysis.json")

    def analysis_deadcode_path_for(self, source_path: Path) -> Path:
        """Return the dead-code analysis JSON path for a given source file."""

        relative = self._to_relative(source_path)
        return self.analysis_root / "dead-code" / (str(relative) + ".deadcode.json")

    def analysis_plumbing_path_for(self, source_path: Path) -> Path:
        """Return the plumbing analysis JSON path for a given source file."""

        relative = self._to_relative(source_path)
        return self.analysis_root / "plumbing" / (str(relative) + ".plumbing.json")

    def analysis_junk_path_for(self, analyzer_name: str, source_path: Path) -> Path:
        """Return the junk analysis JSON path for a given source file and analyzer."""

        relative = self._to_relative(source_path)
        return self.analysis_root / "junk" / analyzer_name / (str(relative) + f".{analyzer_name}.json")

    def signatures_path_for(self, source_path: Path) -> Path:
        """Return the signature JSON path for a given source file."""

        relative = self._to_relative(source_path)
        return self.root_path / SHADOW_DIR / "signatures" / (str(relative) + ".signature.json")

    def signatures_path_for_dir(self, dir_path: Path) -> Path:
        """Return the signature JSON path for a directory."""

        relative = self._to_relative(dir_path)
        if relative == Path("."):
            return self.root_path / SHADOW_DIR / "signatures" / "_directory.signature.json"
        return self.root_path / SHADOW_DIR / "signatures" / relative / "_directory.signature.json"

    @property
    def scorecard_path(self) -> Path:
        """Return the path to the scorecard JSON."""

        return self.analysis_root / "scorecard.json"

    @property
    def staleness_manifest_path(self) -> Path:
        """Return the path to the staleness manifest JSON."""

        return self.root_path / SHADOW_DIR / "staleness.json"

    @property
    def rules_path(self) -> Path:
        """Path to natural language rules file."""

        return self.root_path / SHADOW_DIR / "rules"

    @property
    def ignore_path(self) -> Path:
        """Path to .osojiignore file."""

        return self.root_path / ".osojiignore"

    def load_rules_text(self) -> str:
        """Load raw rules text from .osoji/rules.

        Returns empty string if file doesn't exist.
        LLM interprets the natural language directly.
        """

        if not self.rules_path.exists():
            return ""
        return self.rules_path.read_text(encoding="utf-8")

    def load_osojiignore(self) -> list[str]:
        """Load patterns from .osojiignore (fnmatch patterns on paths).

        Supports negation: lines starting with ! remove that pattern
        from the default ignore_patterns. E.g. "!registry" would
        stop ignoring directories named "registry".
        """

        if not self.ignore_path.exists():
            return []
        content = self.ignore_path.read_text(encoding="utf-8")
        extra_patterns: list[str] = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("!"):
                # Negation: remove from default ignore patterns
                negated = line[1:].strip("/")
                if negated:
                    self.ignore_patterns.discard(negated)
            else:
                normalized = line.strip("/")
                if normalized:
                    extra_patterns.append(normalized)
        return extra_patterns
    def is_doc_candidate(self, path: Path) -> bool:
        """Check if a path is a documentation file candidate.

        Matches based on:
        - Extension (.md, .markdown, .rst, .txt)
        - Filename (README, CHANGELOG, etc. regardless of extension)
        - Location (files in docs/ directory)
        """
        try:
            relative = path.relative_to(self.root_path) if path.is_absolute() else path
        except ValueError:
            relative = path

        # Check extension
        if relative.suffix.lower() in self.doc_extensions:
            return True

        # Check filename (without extension)
        if relative.stem.upper() in {f.upper() for f in self.doc_filenames}:
            return True

        # Check if in a doc directory
        for parent in relative.parents:
            if parent.name.lower() in {d.lower() for d in self.doc_directories}:
                return True
        return False
