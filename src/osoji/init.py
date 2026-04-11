"""Interactive project setup for Osoji."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import click

from .config import BUILTIN_PROVIDER_MODELS, PROJECT_CONFIG_FILENAME
from .llm.registry import get_provider_spec, provider_names
from .push import _infer_project_from_git_remote

_GITIGNORE_ENTRIES: list[tuple[str, str]] = [
    (".osoji/", "intermediate results and derived data"),
    (".osoji.local.toml", "local config overrides"),
    (".env", "secrets file"),
]

# Display order and one-liner descriptions for provider selection.
_PROVIDER_MENU: list[tuple[str, str]] = [
    ("anthropic", "Claude models, built-in defaults"),
    ("openai", "GPT models, built-in defaults"),
    ("google", "Gemini models, built-in defaults"),
    ("openrouter", "Multi-provider gateway, built-in defaults"),
    ("claude-code", "Uses your Claude Code subscription (no API key needed)"),
]


def merge_gitignore(root: Path) -> list[dict[str, str]]:
    """Ensure .gitignore has osoji entries. Returns actions taken per entry."""

    gitignore_path = root / ".gitignore"
    existing_lines: set[str] = set()
    original = ""

    if gitignore_path.exists():
        original = gitignore_path.read_text(encoding="utf-8")
        existing_lines = {line.strip() for line in original.splitlines()}

    actions: list[dict[str, str]] = []
    to_add: list[str] = []

    for pattern, description in _GITIGNORE_ENTRIES:
        if pattern in existing_lines:
            actions.append({"entry": pattern, "action": "skipped", "reason": "already in .gitignore"})
        else:
            to_add.append(pattern)
            actions.append({"entry": pattern, "action": "added", "description": description})

    if to_add:
        lines: list[str] = []
        if original and not original.endswith("\n"):
            lines.append("")
        lines.append("")
        lines.append("# Osoji")
        lines.extend(to_add)
        lines.append("")

        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

    return actions


def _parse_env_keys(content: str) -> set[str]:
    """Extract active (non-commented) variable names from .env content."""

    keys: set[str] = set()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=", stripped)
            if match:
                keys.add(match.group(1))
    return keys


def merge_dotenv(root: Path, values: dict[str, str]) -> list[dict[str, str]]:
    """Merge key=value pairs into .env, skipping keys already present.

    Empty values are written as commented-out lines (# KEY=).
    """

    env_path = root / ".env"
    existing_keys: set[str] = set()
    original = ""

    if env_path.exists():
        original = env_path.read_text(encoding="utf-8")
        existing_keys = _parse_env_keys(original)

    actions: list[dict[str, str]] = []
    lines_to_add: list[str] = []

    # Also track commented-out placeholders to avoid duplicating them
    commented_keys: set[str] = set()
    if original:
        for line in original.splitlines():
            stripped = line.strip()
            cm = re.match(r"#\s*([A-Za-z_][A-Za-z0-9_]*)=", stripped)
            if cm:
                commented_keys.add(cm.group(1))

    for key, value in values.items():
        if key in existing_keys:
            actions.append({"key": key, "action": "skipped", "reason": "already set in .env"})
        elif not value and key in commented_keys:
            actions.append({"key": key, "action": "skipped", "reason": "placeholder already in .env"})
        else:
            if value:
                lines_to_add.append(f"{key}={value}")
            else:
                lines_to_add.append(f"# {key}=")
            actions.append({"key": key, "action": "added"})

    if lines_to_add:
        parts: list[str] = []
        if original and not original.endswith("\n"):
            parts.append("")
        parts.extend(lines_to_add)
        parts.append("")

        with open(env_path, "a", encoding="utf-8") as f:
            f.write("\n".join(parts))

    return actions


def _escape_toml_string(value: str) -> str:
    """Escape a string for TOML double-quoted representation."""

    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _serialize_toml(data: dict) -> str:
    """Serialize a dict to TOML text.

    Handles the flat structure used by .osoji.toml and .osoji.local.toml:
    top-level string keys, one-level table sections, and two-level dotted
    table sections.  All leaf values must be strings.
    """

    if not data:
        return ""

    parts: list[str] = []

    # 1. Top-level scalar keys
    for key, value in data.items():
        if isinstance(value, str):
            parts.append(f'{key} = "{_escape_toml_string(value)}"')

    # 2. One-level table sections (values are dicts of strings)
    for key, value in data.items():
        if isinstance(value, dict) and all(isinstance(v, str) for v in value.values()):
            if parts:
                parts.append("")
            parts.append(f"[{key}]")
            for k, v in value.items():
                parts.append(f'{k} = "{_escape_toml_string(v)}"')

    # 3. Two-level dotted sections (values are dicts of dicts of strings)
    for key, value in data.items():
        if isinstance(value, dict) and any(isinstance(v, dict) for v in value.values()):
            for subkey, subvalue in value.items():
                if isinstance(subvalue, dict):
                    if parts:
                        parts.append("")
                    parts.append(f"[{key}.{subkey}]")
                    for k, v in subvalue.items():
                        parts.append(f'{k} = "{_escape_toml_string(v)}"')

    parts.append("")
    return "\n".join(parts)


def _read_toml(toml_path: Path) -> dict:
    """Read and parse a TOML file, returning {} on missing or corrupt files."""

    if not toml_path.exists():
        return {}
    try:
        return tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}


def _write_toml(toml_path: Path, data: dict) -> None:
    """Serialize *data* and write it to *toml_path*."""

    with open(toml_path, "w", encoding="utf-8") as f:
        f.write(_serialize_toml(data))


def merge_project_toml(root: Path, *, project_slug: str | None) -> list[dict[str, str]]:
    """Ensure .osoji.toml has a [push] project entry."""

    if not project_slug:
        return [{"key": "push.project", "action": "skipped", "reason": "no project slug provided"}]

    toml_path = root / PROJECT_CONFIG_FILENAME
    data = _read_toml(toml_path)

    push = data.get("push")
    if isinstance(push, dict) and "project" in push:
        return [{"key": "push.project", "action": "skipped",
                 "reason": f"already set in {PROJECT_CONFIG_FILENAME}"}]

    data.setdefault("push", {})["project"] = project_slug
    _write_toml(toml_path, data)

    return [{"key": "push.project", "action": "added"}]


def merge_provider_toml(
    root: Path,
    *,
    provider: str,
    models: dict[str, str] | None = None,
    use_local: bool = False,
) -> list[dict[str, str]]:
    """Write provider config to a toml file.

    Writes ``default_provider`` and optionally ``[providers.<name>]`` model
    overrides.  *models* should only contain values that differ from the
    built-in defaults (callers should filter before calling).

    Parameters
    ----------
    use_local:
        If True, write to ``.osoji.local.toml`` instead of ``.osoji.toml``.
    """

    filename = ".osoji.local.toml" if use_local else PROJECT_CONFIG_FILENAME
    toml_path = root / filename
    data = _read_toml(toml_path)

    actions: list[dict[str, str]] = []

    # --- default_provider ---
    if data.get("default_provider") == provider:
        actions.append({
            "key": "default_provider",
            "action": "skipped",
            "reason": f"already set in {filename}",
        })
    else:
        actions.append({"key": "default_provider", "action": "added"})

    # --- model overrides ---
    if models:
        existing_provider = data.get("providers", {}).get(provider, {})
        for tier, model in models.items():
            if existing_provider.get(tier) == model:
                actions.append({
                    "key": f"providers.{provider}.{tier}",
                    "action": "skipped",
                    "reason": f"already set in {filename}",
                })
            else:
                actions.append({
                    "key": f"providers.{provider}.{tier}",
                    "action": "added",
                })

    # Only write if there's something new
    added = [a for a in actions if a["action"] == "added"]
    if not added:
        return actions

    # Merge into dict
    if any(a["key"] == "default_provider" and a["action"] == "added" for a in actions):
        data["default_provider"] = provider

    if models:
        for tier, model in models.items():
            key = f"providers.{provider}.{tier}"
            if any(a["key"] == key and a["action"] == "added" for a in actions):
                data.setdefault("providers", {}).setdefault(provider, {})[tier] = model

    _write_toml(toml_path, data)

    return actions


def _prompt_provider_selection() -> str:
    """Show numbered provider list and return the chosen provider name."""

    click.echo("   Choose your LLM provider:")
    click.echo()
    for i, (name, description) in enumerate(_PROVIDER_MENU, 1):
        spec = get_provider_spec(name)
        click.echo(f"     {i}. {spec.display_name:<18} {description}")
    click.echo()

    choice = click.prompt(
        "   Provider",
        type=click.IntRange(1, len(_PROVIDER_MENU)),
        default=1,
    )
    return _PROVIDER_MENU[choice - 1][0]


def _prompt_model_defaults(provider: str) -> dict[str, str] | None:
    """Show model defaults and let the user accept or override.

    Returns a dict of overridden tiers (only values that differ from
    built-in defaults), or None if defaults were accepted.
    """

    defaults = BUILTIN_PROVIDER_MODELS.get(provider)
    if not defaults:
        return None

    click.echo()
    spec = get_provider_spec(provider)
    click.echo(f"   Model defaults for {spec.display_name}:")
    click.echo(f"     small:  {defaults['small']}")
    click.echo(f"     medium: {defaults['medium']}")
    click.echo(f"     large:  {defaults['large']}")

    if click.confirm("   Accept defaults?", default=True):
        return None

    overrides: dict[str, str] = {}
    for tier in ("small", "medium", "large"):
        value = click.prompt(f"   {tier} model", default=defaults[tier])
        value = value.strip()
        if value != defaults[tier]:
            overrides[tier] = value

    return overrides or None


def _prompt_config_target() -> bool:
    """Ask whether to save to shared or personal config.

    Returns True for .osoji.local.toml, False for .osoji.toml.
    """

    click.echo()
    click.echo("   Save provider config to:")
    click.echo("     1. .osoji.toml        Shared with team, committed to git (Recommended)")
    click.echo("     2. .osoji.local.toml  Personal, gitignored")
    click.echo()
    choice = click.prompt(
        "   Config target",
        type=click.IntRange(1, 2),
        default=1,
    )
    return choice == 2


def run_init(
    *,
    root: Path,
    interactive: bool = True,
    provider: str = "anthropic",
) -> None:
    """Orchestrate osoji project setup."""

    click.echo()
    click.echo("Osoji project setup")
    click.echo("=" * 40)

    # --- 1. Git hygiene ---
    click.echo()
    click.echo(click.style("1. Git hygiene", bold=True))

    if interactive:
        entries_to_add: list[tuple[str, str]] = []

        for pattern, description in _GITIGNORE_ENTRIES:
            gitignore_path = root / ".gitignore"
            existing_lines: set[str] = set()
            if gitignore_path.exists():
                existing_lines = {
                    line.strip()
                    for line in gitignore_path.read_text(encoding="utf-8").splitlines()
                }

            if pattern in existing_lines:
                click.echo(f"   Already in .gitignore: {pattern}")
                continue

            if click.confirm(
                f"   Add {pattern} to .gitignore? ({description})",
                default=True,
            ):
                entries_to_add.append((pattern, description))

        if entries_to_add:
            gitignore_path = root / ".gitignore"
            original = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
            parts: list[str] = []
            if original and not original.endswith("\n"):
                parts.append("")
            parts.append("")
            parts.append("# Osoji")
            for pattern, _ in entries_to_add:
                parts.append(pattern)
            parts.append("")
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n".join(parts))
            for pattern, _ in entries_to_add:
                click.echo(f"   {click.style('ok', fg='green')} Added {pattern}")
    else:
        actions = merge_gitignore(root)
        for a in actions:
            if a["action"] == "added":
                click.echo(f"   {click.style('ok', fg='green')} Added {a['entry']}")
            else:
                click.echo(f"   Already in .gitignore: {a['entry']}")

    # --- 2. Provider setup ---
    click.echo()
    click.echo(click.style("2. Provider setup", bold=True))

    model_overrides: dict[str, str] | None = None
    use_local_config = False

    if interactive:
        # Provider selection (--provider flag pre-selects)
        provider_from_flag = provider != "anthropic"
        if provider_from_flag:
            spec = get_provider_spec(provider)
            click.echo(f"   Provider: {spec.display_name} (from --provider flag)")
        else:
            provider = _prompt_provider_selection()
            spec = get_provider_spec(provider)
            click.echo(f"   Selected: {spec.display_name}")

        # Model defaults (skip for claude-code — it manages models internally)
        if provider != "claude-code":
            model_overrides = _prompt_model_defaults(provider)
        else:
            click.echo("   Claude Code manages model selection internally.")

        # Config target
        use_local_config = _prompt_config_target()
    else:
        spec = get_provider_spec(provider)
        click.echo(f"   Provider: {spec.display_name} (built-in defaults)")

    # Write provider config
    provider_actions = merge_provider_toml(
        root,
        provider=provider,
        models=model_overrides,
        use_local=use_local_config,
    )
    target_file = ".osoji.local.toml" if use_local_config else PROJECT_CONFIG_FILENAME
    for a in provider_actions:
        if a["action"] == "added":
            click.echo(f"   {click.style('ok', fg='green')} Set {a['key']} in {target_file}")
        else:
            click.echo(f"   Skipping {a['key']} ({a['reason']})")

    # Guidance
    click.echo()
    click.echo("   Tip: To switch providers later, set default_provider in your config file:")
    click.echo(f'     default_provider = "{provider}"')
    click.echo("   Or set OSOJI_PROVIDER and OSOJI_MODEL environment variables.")
    click.echo("   Run `osoji config show` to see your current configuration.")

    # --- 3. Secrets (.env) ---
    click.echo()
    click.echo(click.style("3. Secrets (.env)", bold=True))

    api_key_env = spec.api_key_env
    env_values: dict[str, str] = {}

    if interactive:
        env_path = root / ".env"
        existing_keys: set[str] = set()
        if env_path.exists():
            existing_keys = _parse_env_keys(env_path.read_text(encoding="utf-8"))

        if provider == "claude-code":
            click.echo("   Claude Code uses your existing subscription. No API key needed.")
        elif api_key_env:
            if api_key_env in existing_keys:
                click.echo(f"   Skipping {api_key_env} in .env (already set)")
            elif click.confirm(f"   Set {api_key_env}?", default=True):
                value = click.prompt(f"   {api_key_env}", default="", hide_input=True)
                env_values[api_key_env] = value
            else:
                click.echo(f"   Skipped. Add your API key later in .env:")
                click.echo(f"     {api_key_env}=<your-key>")
                click.echo(f"   Or set it as an environment variable.")

        if "OSOJI_TOKEN" in existing_keys:
            click.echo(f"   Skipping OSOJI_TOKEN in .env (already set)")
        elif click.confirm("   Set OSOJI_TOKEN? (needed for `osoji push`)", default=True):
            value = click.prompt("   OSOJI_TOKEN", default="", hide_input=True)
            env_values["OSOJI_TOKEN"] = value

        if env_values:
            env_actions = merge_dotenv(root, env_values)
            for a in env_actions:
                if a["action"] == "added":
                    click.echo(f"   {click.style('ok', fg='green')} Added {a['key']} to .env")
                else:
                    click.echo(f"   Skipping {a['key']} in .env ({a['reason']})")
        elif not existing_keys and provider != "claude-code":
            click.echo("   No secrets configured.")
    else:
        if api_key_env:
            env_values[api_key_env] = ""
        env_values["OSOJI_TOKEN"] = ""
        actions = merge_dotenv(root, env_values)
        for a in actions:
            if a["action"] == "added":
                click.echo(f"   {click.style('ok', fg='green')} Added {a['key']} to .env (placeholder)")
            else:
                click.echo(f"   Skipping {a['key']} in .env ({a['reason']})")

    # --- 4. Project config (.osoji.toml) ---
    click.echo()
    click.echo(click.style("4. Project config (.osoji.toml)", bold=True))

    inferred_slug = _infer_project_from_git_remote(root)

    if interactive:
        default_slug = inferred_slug or ""
        project_slug = click.prompt(
            "   Project slug (for `osoji push`)",
            default=default_slug,
        )
        project_slug = project_slug.strip() or None
    else:
        project_slug = inferred_slug

    toml_actions = merge_project_toml(root, project_slug=project_slug)
    for a in toml_actions:
        if a["action"] == "added":
            click.echo(f"   {click.style('ok', fg='green')} Set [push] project = \"{project_slug}\" in .osoji.toml")
        else:
            click.echo(f"   Skipping {a['key']} ({a['reason']})")

    # --- Done ---
    click.echo()
    click.echo(click.style("Done!", bold=True) + " Next steps:")
    click.echo("  osoji audit . --dry-run    Preview what osoji will analyze")
    click.echo("  osoji audit .              Run a full audit")
    click.echo("  osoji config show          See resolved configuration")
    click.echo()
