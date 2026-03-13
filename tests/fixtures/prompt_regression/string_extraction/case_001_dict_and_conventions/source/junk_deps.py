"""Dead dependency detection via manifest parsing and import scanning."""

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult
from .llm.base import LLMProvider
from .llm.types import Message, MessageRole, CompletionOptions
from .rate_limiter import RateLimiter
from .tools import get_dead_deps_tool_definitions, get_resolve_import_names_tool_definitions, get_classify_deps_tool_definitions
from .walker import list_repo_files, _matches_ignore

HAIKU_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class DependencyCandidate:
    """A dependency that may be unused."""

    manifest_path: str        # e.g. "pyproject.toml"
    package_name: str
    import_names: list[str]   # resolved import names (may differ from package name)
    import_hits: int = 0      # count of source files importing this
    hit_files: list[str] = field(default_factory=list)
    is_dev: bool = False
    ecosystem: str = "python"
    line_number: int = 1


@dataclass
class DepVerification:
    """Result of verifying whether a dependency is dead."""

    manifest_path: str
    package_name: str
    is_dead: bool
    confidence: float
    reason: str
    remediation: str
    usage_type: str
    line_number: int


# --- Known package name -> import name mismatches (zero-cost cache) ---

_IMPORT_NAME_CACHE: dict[str, list[str]] = {
    "pillow": ["PIL"],
    "scikit-learn": ["sklearn"],
    "pyyaml": ["yaml"],
    "beautifulsoup4": ["bs4"],
    "python-dateutil": ["dateutil"],
    "pyjwt": ["jwt"],
    "opencv-python": ["cv2"],
    "opencv-python-headless": ["cv2"],
    "python-dotenv": ["dotenv"],
    "attrs": ["attr", "attrs"],
    "protobuf": ["google.protobuf", "google"],
    "grpcio": ["grpc"],
    "pymongo": ["pymongo", "bson"],
    "python-magic": ["magic"],
    "python-multipart": ["multipart"],
    "python-jose": ["jose"],
    "ruamel.yaml": ["ruamel"],
    "msgpack-python": ["msgpack"],
    "pyzmq": ["zmq"],
    "websocket-client": ["websocket"],
    "gitpython": ["git"],
    "python-slugify": ["slugify"],
    "py": ["py"],
    "pycryptodome": ["Crypto"],
    "pynacl": ["nacl"],
}

# --- Build tools cache (fast pre-filter before Haiku classification) ---

_BUILD_TOOLS_CACHE: set[str] = {
    # Python build tools
    "black", "ruff", "isort", "flake8", "pylint", "mypy", "pyright",
    "pytest", "tox", "nox", "pre-commit", "twine", "build", "setuptools",
    "wheel", "pip", "pip-tools", "sphinx", "mkdocs", "coverage", "bandit",
    "autopep8", "yapf", "pyflakes", "pycodestyle", "pydocstyle",
    "flit", "hatch", "hatchling", "poetry", "poetry-core",
    "maturin", "setuptools-scm", "setuptools-rust", "cython",
    "bump2version", "bumpversion", "towncrier",
    "sphinx-rtd-theme", "sphinx-autodoc-typehints",
    "pytest-cov", "pytest-xdist", "pytest-asyncio", "pytest-mock",
    "pytest-timeout", "pytest-randomly", "pytest-sugar",
    "ipython", "ipdb", "debugpy",
    # Node build tools
    "typescript", "ts-node", "tsx", "esbuild", "webpack", "rollup", "vite",
    "parcel", "turbo", "eslint", "prettier", "jest", "mocha", "vitest",
    "cypress", "playwright", "rimraf", "nodemon", "husky", "lint-staged",
    "concurrently", "cross-env", "dotenv-cli", "ts-jest",
    "@types/node", "@types/jest", "@types/mocha",
    "babel-jest", "identity-obj-proxy",
    "postcss", "autoprefixer", "tailwindcss", "sass", "less",
    "webpack-cli", "webpack-dev-server",
    "@babel/core", "@babel/cli", "@babel/preset-env", "@babel/preset-typescript",
    "terser", "cssnano", "mini-css-extract-plugin",
}


def _resolve_import_names_heuristic(package_name: str, ecosystem: str) -> list[str]:
    """Map package name to importable name(s)."""
    lower = package_name.lower()

    if ecosystem == "python":
        if lower in _IMPORT_NAME_CACHE:
            return _IMPORT_NAME_CACHE[lower]
        # Heuristic: lowercase, hyphens to underscores
        return [lower.replace("-", "_")]

    if ecosystem == "node":
        return [package_name]  # Use exact name including scoped packages

    if ecosystem == "rust":
        return [package_name.replace("-", "_")]

    if ecosystem == "go":
        # Last path segment of module path
        parts = package_name.rsplit("/", 1)
        return [parts[-1]]

    return [lower.replace("-", "_")]



# --- Haiku-backed import name resolution ---

_RESOLVE_IMPORTS_SYSTEM_PROMPT = """You are a package name resolution expert. For each package, return the importable module name(s) that would appear in import statements.

Be precise — many packages have import names that differ from their package names:
- Python: pillow->PIL, scikit-learn->sklearn, pyyaml->yaml, beautifulsoup4->bs4
- Rust: hyphens become underscores (serde-json->serde_json)
- Node: scoped packages keep their scope (@scope/pkg)
- Go: last path segment of module path

If unsure, use the standard heuristic: lowercase, hyphens to underscores.

Provide a resolution for EVERY package listed."""


async def _resolve_import_names_batch_async(
    provider: LLMProvider,
    packages: list[tuple[str, str]],  # (package_name, ecosystem)
) -> tuple[dict[str, list[str]], int, int]:
    """Batch Haiku call to resolve package names to import names.

    Returns (package_name -> import_names, input_tokens, output_tokens).
    """
    if not packages:
        return {}, 0, 0

    # Build user message
    lines = ["Resolve these packages to their importable module names:\n"]
    for pkg, eco in packages:
        lines.append(f"- `{pkg}` ({eco})")

    pkg_names = [pkg for pkg, _ in packages]
    lines.append(f"\nProvide a resolution for EVERY package: {', '.join(f'`{p}`' for p in pkg_names)}")

    expected = {pkg for pkg, _ in packages}

    def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
        if tool_name != "resolve_import_names":
            return []
        resolutions = tool_input.get("resolutions", [])
        got = {r.get("package_name") for r in resolutions}
        missing = expected - got
        return [f"Missing resolution for package '{n}'" for n in sorted(missing)]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(lines))],
        system=_RESOLVE_IMPORTS_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=HAIKU_MODEL,
            max_tokens=max(1024, len(packages) * 50),
            tools=get_resolve_import_names_tool_definitions(),
            tool_choice={"type": "tool", "name": "resolve_import_names"},
            tool_input_validators=[check_completeness],
        ),
    )

    resolved: dict[str, list[str]] = {}
    for tc in result.tool_calls:
        if tc.name == "resolve_import_names":
            for r in tc.input.get("resolutions", []):
                pkg = r.get("package_name", "")
                names = r.get("import_names", [])
                if pkg and names:
                    resolved[pkg] = names

    return resolved, result.input_tokens, result.output_tokens


# --- Haiku-backed dependency classification ---

_CLASSIFY_DEPS_SYSTEM_PROMPT = """You are a dependency usage classifier. For each zero-import dependency, determine HOW it is used based on its name and ecosystem context.

Be conservative — if a package is clearly a build tool, linter, formatter, test framework, type stub, or plugin, classify it accordingly to avoid false positives in dead dependency detection.

Only classify as `genuine_candidate` if the package does not fit any other category."""


async def _classify_deps_batch_async(
    provider: LLMProvider,
    candidates: list[DependencyCandidate],
    manifest_content: str,
) -> tuple[list[DependencyCandidate], dict[str, str], int, int]:
    """Batch Haiku call to classify zero-import dependencies.

    Returns (genuine_candidates, classification_map, input_tokens, output_tokens).
    """
    if not candidates:
        return [], {}, 0, 0

    lines = [f"## Manifest context\n```\n{manifest_content[:10000]}\n```\n"]
    lines.append("## Zero-import dependencies to classify\n")
    for c in candidates:
        dev_tag = " (dev)" if c.is_dev else ""
        lines.append(f"- `{c.package_name}`{dev_tag} ({c.ecosystem})")

    pkg_names = [c.package_name for c in candidates]
    lines.append(f"\nClassify EVERY dependency: {', '.join(f'`{p}`' for p in pkg_names)}")

    expected = {c.package_name for c in candidates}

    def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
        if tool_name != "classify_deps":
            return []
        classifications = tool_input.get("classifications", [])
        got = {c.get("package_name") for c in classifications}
        missing = expected - got
        return [f"Missing classification for '{n}'" for n in sorted(missing)]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(lines))],
        system=_CLASSIFY_DEPS_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=HAIKU_MODEL,
            max_tokens=max(1024, len(candidates) * 80),
            tools=get_classify_deps_tool_definitions(),
            tool_choice={"type": "tool", "name": "classify_deps"},
            tool_input_validators=[check_completeness],
        ),
    )

    classification_map: dict[str, str] = {}
    for tc in result.tool_calls:
        if tc.name == "classify_deps":
            for c in tc.input.get("classifications", []):
                pkg = c.get("package_name", "")
                cls = c.get("classification", "genuine_candidate")
                if pkg:
                    classification_map[pkg] = cls

    genuine = [c for c in candidates if classification_map.get(c.package_name) == "genuine_candidate"]
    return genuine, classification_map, result.input_tokens, result.output_tokens


# --- Manifest discovery ---

_MANIFEST_FILES: dict[str, str] = {
    "pyproject.toml": "python",
    "setup.cfg": "python",
    "Pipfile": "python",
    "package.json": "node",
    "Cargo.toml": "rust",
    "go.mod": "go",
}

_REQUIREMENTS_PATTERN = re.compile(r"^requirements(?:-\w+)?\.txt$")


def discover_manifests(config: Config) -> list[tuple[str, str]]:
    """Scan repo root for known manifest filenames.

    Returns list of (relative_path, ecosystem).
    """
    manifests: list[tuple[str, str]] = []

    # Check fixed filenames at root
    for filename, ecosystem in _MANIFEST_FILES.items():
        if (config.root_path / filename).is_file():
            manifests.append((filename, ecosystem))

    # Check requirements*.txt patterns
    for child in config.root_path.iterdir():
        if child.is_file() and _REQUIREMENTS_PATTERN.match(child.name):
            manifests.append((child.name, "python"))

    return manifests


# --- Manifest parsers ---

def _parse_requirements_txt(content: str, path: str) -> list[DependencyCandidate]:
    """Parse requirements.txt format."""
    candidates: list[DependencyCandidate] = []
    for line_num, line in enumerate(content.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Skip directives
        if line.startswith(("-r", "-c", "-e", "-f", "--")):
            continue
        # Strip version specifiers, extras, markers
        # Package name is everything before first version specifier or extra
        match = re.match(r"([A-Za-z0-9][\w.\-]*)", line)
        if match:
            pkg = match.group(1).strip(".")
            if pkg:
                candidates.append(DependencyCandidate(
                    manifest_path=path,
                    package_name=pkg,
                    import_names=_resolve_import_names_heuristic(pkg, "python"),
                    ecosystem="python",
                    line_number=line_num,
                ))
    return candidates


def _parse_pyproject_toml(content: str, path: str) -> list[DependencyCandidate]:
    """Parse pyproject.toml for Python dependencies."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return []

    try:
        data = tomllib.loads(content)
    except Exception:
        return []

    candidates: list[DependencyCandidate] = []
    lines = content.splitlines()

    def _find_line(pkg_name: str) -> int:
        """Find approximate line number for a package in the TOML file."""
        lower = pkg_name.lower()
        for i, line in enumerate(lines, 1):
            if lower in line.lower():
                return i
        return 1

    def _extract_pkg_name(spec: str) -> str:
        """Extract package name from a PEP 508 dependency specifier."""
        match = re.match(r"([A-Za-z0-9][\w.\-]*)", spec)
        return match.group(1) if match else ""

    # project.dependencies
    for spec in data.get("project", {}).get("dependencies", []):
        pkg = _extract_pkg_name(spec)
        if pkg:
            candidates.append(DependencyCandidate(
                manifest_path=path, package_name=pkg,
                import_names=_resolve_import_names_heuristic(pkg, "python"),
                ecosystem="python", line_number=_find_line(pkg),
            ))

    # project.optional-dependencies
    for group_deps in data.get("project", {}).get("optional-dependencies", {}).values():
        for spec in group_deps:
            pkg = _extract_pkg_name(spec)
            if pkg:
                candidates.append(DependencyCandidate(
                    manifest_path=path, package_name=pkg,
                    import_names=_resolve_import_names_heuristic(pkg, "python"),
                    ecosystem="python", line_number=_find_line(pkg), is_dev=True,
                ))

    # tool.poetry.dependencies / tool.poetry.group.*.dependencies
    poetry = data.get("tool", {}).get("poetry", {})
    for pkg in poetry.get("dependencies", {}):
        if pkg.lower() == "python":
            continue
        candidates.append(DependencyCandidate(
            manifest_path=path, package_name=pkg,
            import_names=_resolve_import_names_heuristic(pkg, "python"),
            ecosystem="python", line_number=_find_line(pkg),
        ))
    for group_data in poetry.get("group", {}).values():
        for pkg in group_data.get("dependencies", {}):
            if pkg.lower() == "python":
                continue
            candidates.append(DependencyCandidate(
                manifest_path=path, package_name=pkg,
                import_names=_resolve_import_names_heuristic(pkg, "python"),
                ecosystem="python", line_number=_find_line(pkg), is_dev=True,
            ))

    # build-system.requires
    for spec in data.get("build-system", {}).get("requires", []):
        pkg = _extract_pkg_name(spec)
        if pkg:
            candidates.append(DependencyCandidate(
                manifest_path=path, package_name=pkg,
                import_names=_resolve_import_names_heuristic(pkg, "python"),
                ecosystem="python", line_number=_find_line(pkg), is_dev=True,
            ))

    return candidates


def _parse_package_json(content: str, path: str) -> list[DependencyCandidate]:
    """Parse package.json for Node dependencies."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []

    candidates: list[DependencyCandidate] = []
    lines = content.splitlines()

    def _find_line(pkg_name: str) -> int:
        for i, line in enumerate(lines, 1):
            if f'"{pkg_name}"' in line:
                return i
        return 1

    for section, is_dev in [
        ("dependencies", False),
        ("devDependencies", True),
        ("peerDependencies", False),
    ]:
        for pkg in data.get(section, {}):
            candidates.append(DependencyCandidate(
                manifest_path=path, package_name=pkg,
                import_names=_resolve_import_names_heuristic(pkg, "node"),
                ecosystem="node", line_number=_find_line(pkg), is_dev=is_dev,
            ))

    return candidates


def _parse_cargo_toml(content: str, path: str) -> list[DependencyCandidate]:
    """Parse Cargo.toml for Rust dependencies."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return []

    try:
        data = tomllib.loads(content)
    except Exception:
        return []

    candidates: list[DependencyCandidate] = []
    lines = content.splitlines()

    def _find_line(pkg_name: str) -> int:
        for i, line in enumerate(lines, 1):
            if pkg_name in line:
                return i
        return 1

    for section, is_dev in [("dependencies", False), ("dev-dependencies", True)]:
        for pkg, value in data.get(section, {}).items():
            # Handle package renames: {package = "actual-name", ...}
            actual_name = pkg
            if isinstance(value, dict) and "package" in value:
                actual_name = value["package"]
            candidates.append(DependencyCandidate(
                manifest_path=path, package_name=pkg,
                import_names=_resolve_import_names_heuristic(actual_name, "rust"),
                ecosystem="rust", line_number=_find_line(pkg), is_dev=is_dev,
            ))

    return candidates


def _parse_go_mod(content: str, path: str) -> list[DependencyCandidate]:
    """Parse go.mod for Go dependencies."""
    candidates: list[DependencyCandidate] = []

    # Match both single-line and block require
    # Single: require github.com/foo/bar v1.2.3
    # Block: require ( \n  github.com/foo/bar v1.2.3 \n )
    in_require_block = False
    for line_num, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()

        if stripped.startswith("require ("):
            in_require_block = True
            continue
        if in_require_block and stripped == ")":
            in_require_block = False
            continue

        if in_require_block:
            match = re.match(r"(\S+)\s+\S+", stripped)
            if match:
                mod_path = match.group(1)
                candidates.append(DependencyCandidate(
                    manifest_path=path, package_name=mod_path,
                    import_names=_resolve_import_names_heuristic(mod_path, "go"),
                    ecosystem="go", line_number=line_num,
                ))
        elif stripped.startswith("require ") and "(" not in stripped:
            match = re.match(r"require\s+(\S+)\s+\S+", stripped)
            if match:
                mod_path = match.group(1)
                candidates.append(DependencyCandidate(
                    manifest_path=path, package_name=mod_path,
                    import_names=_resolve_import_names_heuristic(mod_path, "go"),
                    ecosystem="go", line_number=line_num,
                ))

    return candidates


_PARSERS: dict[str, Callable] = {
    "requirements.txt": _parse_requirements_txt,
    "pyproject.toml": _parse_pyproject_toml,
    "setup.cfg": _parse_requirements_txt,  # close enough for dependency lines
    "Pipfile": _parse_requirements_txt,    # rough approximation
    "package.json": _parse_package_json,
    "Cargo.toml": _parse_cargo_toml,
    "go.mod": _parse_go_mod,
}


def parse_manifest(content: str, path: str) -> list[DependencyCandidate]:
    """Parse a manifest file and return dependency candidates."""
    # Find parser by filename
    filename = Path(path).name
    if filename in _PARSERS:
        return _PARSERS[filename](content, path)
    # Requirements-like files
    if _REQUIREMENTS_PATTERN.match(filename):
        return _parse_requirements_txt(content, path)
    return []


# --- Import scanning ---

def scan_imports(
    config: Config,
    candidates: list[DependencyCandidate],
) -> list[DependencyCandidate]:
    """Scan all source files for imports matching candidate dependencies.

    Updates import_hits and hit_files on each candidate. Returns all candidates.
    """
    if not candidates:
        return candidates

    # Build pattern: map import_name -> list of candidate indices
    import_to_candidates: dict[str, list[int]] = {}
    for idx, cand in enumerate(candidates):
        for imp_name in cand.import_names:
            import_to_candidates.setdefault(imp_name, []).append(idx)

    # Build regex for all import names
    all_import_names = sorted(import_to_candidates.keys(), key=len, reverse=True)
    if not all_import_names:
        return candidates

    escaped = [re.escape(name) for name in all_import_names]
    pattern = re.compile(r"\b(" + "|".join(escaped) + r")\b")

    # Scan all repo files
    all_paths, _ = list_repo_files(config)
    osojiignore = config.load_osojiignore()

    for path in all_paths:
        if not path.is_absolute():
            path = config.root_path / path

        if not path.is_file():
            continue

        relative = path.relative_to(config.root_path)
        rel_str = str(relative).replace("\\", "/")

        if rel_str.startswith(".osoji"):
            continue
        if _matches_ignore(relative, config.ignore_patterns):
            continue
        if osojiignore and _matches_ignore(relative, osojiignore):
            continue

        # Skip manifest files themselves
        if rel_str in {c.manifest_path for c in candidates}:
            continue

        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue

        # Find all import name matches in this file
        found_names: set[str] = set()
        for match in pattern.finditer(content):
            found_names.add(match.group(1))

        for name in found_names:
            for idx in import_to_candidates.get(name, []):
                if rel_str not in candidates[idx].hit_files:
                    candidates[idx].hit_files.append(rel_str)
                    candidates[idx].import_hits += 1

    return candidates


def _filter_zero_import(candidates: list[DependencyCandidate]) -> list[DependencyCandidate]:
    """Return only candidates where import_hits == 0."""
    return [c for c in candidates if c.import_hits == 0]



# --- LLM verification ---

_DEAD_DEPS_SYSTEM_PROMPT = """You are analyzing package dependencies to determine which are truly unused.

You are given a manifest file and a list of dependencies that have zero import matches in the source code. For each dependency, determine whether it is genuinely unused or alive through non-import usage.

## Non-import usage patterns (dependency is ALIVE)
- **Build tools**: Invoked from CLI or scripts (black, ruff, pytest, eslint, prettier, webpack)
- **Framework plugins**: Auto-discovered by a framework (pytest plugins like pytest-cov, Django apps, Babel plugins, PostCSS plugins)
- **CLI tools**: Provide command-line binaries used in scripts or CI (alembic, celery, gunicorn, nodemon)
- **Type stubs**: @types/* packages used by TypeScript, or typing stubs like types-requests
- **Peer dependencies**: Required by another installed package
- **Build system**: Required by the build backend (setuptools, wheel, hatchling, flit-core)
- **Configuration-only**: Referenced in config files (.eslintrc, babel.config.js, pytest.ini) but not imported

## When a dependency IS dead
- No imports AND no configuration references AND not a build tool/plugin/CLI tool/type package
- Added for a feature that was later removed
- Superseded by another package

Use the verify_dead_deps tool with a verdict for EVERY dependency."""


async def _verify_batch_async(
    provider: LLMProvider,
    config: Config,
    candidates: list[DependencyCandidate],
    manifest_content: str,
    config_snippets: dict[str, str],
) -> tuple[list[DepVerification], int, int]:
    """Verify a batch of dead dependency candidates via one LLM call per manifest.

    Returns (list[DepVerification], input_tokens, output_tokens).
    """
    user_parts: list[str] = []

    manifest_path = candidates[0].manifest_path
    user_parts.append(f"## Manifest file: `{manifest_path}`\n```\n{manifest_content[:50000]}\n```\n")

    user_parts.append("## Zero-import dependencies\n")
    for cand in candidates:
        dev_tag = " (dev)" if cand.is_dev else ""
        user_parts.append(
            f"- `{cand.package_name}`{dev_tag} — import names tried: {cand.import_names} "
            f"(line {cand.line_number})"
        )
    user_parts.append("")

    if config_snippets:
        user_parts.append("## Config file snippets mentioning these packages\n")
        for filepath, snippet in config_snippets.items():
            user_parts.append(f"### `{filepath}`\n```\n{snippet[:5000]}\n```\n")

    names_list = ", ".join(f"`{c.package_name}`" for c in candidates)
    user_parts.append(
        f"Provide a verdict for EVERY dependency listed ({names_list}) "
        "using the verify_dead_deps tool."
    )

    # Build completeness validator
    expected_names = {c.package_name for c in candidates}

    def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
        if tool_name != "verify_dead_deps":
            return []
        verdicts = tool_input.get("verdicts", [])
        got_names = {v.get("package_name") for v in verdicts}
        missing = expected_names - got_names
        return [f"Missing verdict for dependency '{name}'" for name in sorted(missing)]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(user_parts))],
        system=_DEAD_DEPS_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model,
            max_tokens=max(1024, len(candidates) * 200),
            tools=get_dead_deps_tool_definitions(),
            tool_choice={"type": "tool", "name": "verify_dead_deps"},
            tool_input_validators=[check_completeness],
        ),
    )

    verifications: list[DepVerification] = []
    cand_by_name = {c.package_name: c for c in candidates}

    for tool_call in result.tool_calls:
        if tool_call.name == "verify_dead_deps":
            for verdict in tool_call.input.get("verdicts", []):
                pkg_name = verdict.get("package_name", "")
                cand = cand_by_name.get(pkg_name)
                if cand:
                    verifications.append(DepVerification(
                        manifest_path=cand.manifest_path,
                        package_name=cand.package_name,
                        is_dead=verdict["is_dead"],
                        confidence=verdict["confidence"],
                        reason=verdict["reason"],
                        remediation=verdict["remediation"],
                        usage_type=verdict.get("usage_type", "unused"),
                        line_number=cand.line_number,
                    ))

    if not verifications:
        raise RuntimeError(
            f"LLM did not return verdicts for dependencies: "
            f"{[c.package_name for c in candidates]}"
        )

    return verifications, result.input_tokens, result.output_tokens


def _find_config_snippets(
    config: Config,
    candidates: list[DependencyCandidate],
) -> dict[str, str]:
    """Find config files that mention candidate package names."""
    config_patterns = [
        ".eslintrc*", "babel.config*", "jest.config*", ".babelrc",
        "postcss.config*", "tailwind.config*", "vite.config*",
        "webpack.config*", "rollup.config*", "tsconfig*",
        "pytest.ini", "setup.cfg", "tox.ini", ".flake8",
        "mypy.ini", ".pylintrc", "pyproject.toml",
        "Makefile", "GNUmakefile",
    ]

    pkg_names = {c.package_name.lower() for c in candidates}
    snippets: dict[str, str] = {}

    for child in config.root_path.iterdir():
        if not child.is_file():
            continue
        name = child.name
        match = any(
            re.match(p.replace("*", ".*"), name) for p in config_patterns
        )
        if not match:
            continue

        try:
            content = child.read_text(errors="ignore")
        except OSError:
            continue

        lower_content = content.lower()
        if any(pkg in lower_content for pkg in pkg_names):
            snippets[name] = content[:5000]

    return snippets


# --- Full pipeline ---

async def detect_dead_deps_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[DepVerification]:
    """Detect unused dependencies across the project."""
    manifests = discover_manifests(config)
    if not manifests:
        print("  [skip] No manifest files found.", flush=True)
        return []

    print(f"  Found {len(manifests)} manifest file(s)", flush=True)

    # Parse all manifests
    all_candidates: list[DependencyCandidate] = []
    manifest_contents: dict[str, str] = {}

    for manifest_path, ecosystem in manifests:
        full_path = config.root_path / manifest_path
        try:
            content = full_path.read_text(errors="ignore")
        except OSError:
            continue
        manifest_contents[manifest_path] = content
        parsed = parse_manifest(content, manifest_path)
        all_candidates.extend(parsed)

    if not all_candidates:
        print("  No dependencies found in manifests.", flush=True)
        return []

    print(f"  Found {len(all_candidates)} dependency(ies) across all manifests", flush=True)

    # --- Haiku import name resolution ---
    # Collect packages not already in cache
    to_resolve: list[tuple[str, str]] = []
    for cand in all_candidates:
        if cand.package_name.lower() not in _IMPORT_NAME_CACHE:
            to_resolve.append((cand.package_name, cand.ecosystem))

    # Deduplicate
    to_resolve = list(dict.fromkeys(to_resolve))

    if to_resolve:
        try:
            await rate_limiter.throttle()
            # Batch up to 80 per call
            haiku_resolved: dict[str, list[str]] = {}
            for i in range(0, len(to_resolve), 80):
                batch = to_resolve[i:i + 80]
                resolved, in_tok, out_tok = await _resolve_import_names_batch_async(
                    provider, batch,
                )
                rate_limiter.record_usage(input_tokens=in_tok, output_tokens=out_tok)
                haiku_resolved.update(resolved)

            # Update candidate import names with Haiku results
            for cand in all_candidates:
                if cand.package_name in haiku_resolved:
                    cand.import_names = haiku_resolved[cand.package_name]

            print(f"  Haiku resolved import names for {len(haiku_resolved)}/{len(to_resolve)} package(s)", flush=True)
        except Exception as e:
            print(f"  [warn] Haiku import resolution failed, using heuristic: {e}", flush=True)

    # Scan imports
    scan_imports(config, all_candidates)

    # Filter to zero-import candidates
    zero_import = _filter_zero_import(all_candidates)

    # Fast pre-filter: remove known build tools and @types packages
    pre_filtered: list[DependencyCandidate] = []
    for cand in zero_import:
        lower = cand.package_name.lower()
        if lower in _BUILD_TOOLS_CACHE:
            continue
        if cand.ecosystem == "node" and lower.startswith("@types/"):
            continue
        pre_filtered.append(cand)

    print(
        f"  {len(pre_filtered)} zero-import candidate(s) after pre-filter "
        f"(from {len(all_candidates)} total, {len(zero_import)} zero-import)",
        flush=True,
    )

    if not pre_filtered:
        return []

    # --- Haiku dependency classification ---
    # Group by manifest for classification
    by_manifest_classify: dict[str, list[DependencyCandidate]] = {}
    for cand in pre_filtered:
        by_manifest_classify.setdefault(cand.manifest_path, []).append(cand)

    genuine_candidates: list[DependencyCandidate] = []
    for manifest_path, cands in by_manifest_classify.items():
        try:
            await rate_limiter.throttle()
            # Batch up to 50 per call
            for i in range(0, len(cands), 50):
                batch = cands[i:i + 50]
                genuine, _class_map, in_tok, out_tok = await _classify_deps_batch_async(
                    provider, batch, manifest_contents.get(manifest_path, ""),
                )
                rate_limiter.record_usage(input_tokens=in_tok, output_tokens=out_tok)
                genuine_candidates.extend(genuine)
        except Exception as e:
            print(f"  [warn] Haiku classification failed for {manifest_path}, sending all to Sonnet: {e}", flush=True)
            genuine_candidates.extend(cands)

    print(
        f"  {len(genuine_candidates)} genuine candidate(s) for Sonnet verification "
        f"(Haiku filtered {len(pre_filtered) - len(genuine_candidates)})",
        flush=True,
    )

    if not genuine_candidates:
        return []

    # Group candidates by manifest for Sonnet verification
    by_manifest: dict[str, list[DependencyCandidate]] = {}
    for cand in genuine_candidates:
        by_manifest.setdefault(cand.manifest_path, []).append(cand)

    results: list[DepVerification] = []
    semaphore = asyncio.Semaphore(config.max_concurrency)
    completed_manifests = 0
    total_manifests = len(by_manifest)
    lock = asyncio.Lock()

    async def process_manifest(
        manifest_path: str,
        candidates: list[DependencyCandidate],
    ) -> list[DepVerification]:
        nonlocal completed_manifests

        async with semaphore:
            await rate_limiter.throttle()
            try:
                config_snippets = _find_config_snippets(config, candidates)
                verifications, in_tok, out_tok = await _verify_batch_async(
                    provider, config, candidates,
                    manifest_contents.get(manifest_path, ""),
                    config_snippets,
                )
                rate_limiter.record_usage(input_tokens=in_tok, output_tokens=out_tok)

                async with lock:
                    completed_manifests += 1
                    dead_count = sum(1 for v in verifications if v.is_dead)
                    for v in verifications:
                        if v.is_dead:
                            results.append(v)
                    if on_progress:
                        on_progress(
                            completed_manifests, total_manifests,
                            Path(manifest_path),
                            f"{dead_count} dead",
                        )
                return verifications
            except Exception as e:
                async with lock:
                    completed_manifests += 1
                    if on_progress:
                        on_progress(
                            completed_manifests, total_manifests,
                            Path(manifest_path), "error",
                        )
                print(f"  [error] {manifest_path}: {e}", flush=True)
                return []

    tasks = [
        process_manifest(mp, cands)
        for mp, cands in by_manifest.items()
    ]
    await asyncio.gather(*tasks)

    return results


class DeadDepsAnalyzer(JunkAnalyzer):
    """Junk analyzer that detects unused package dependencies."""

    @property
    def name(self) -> str:
        return "dead_deps"

    @property
    def description(self) -> str:
        return "Detect unused package dependencies"

    @property
    def cli_flag(self) -> str:
        return "dead-deps"

    def analyze(self, config, on_progress=None, rate_limiter=None):
        """Sync wrapper — skip symbols-dir check (deps don't need symbols)."""
        from .llm.factory import create_provider
        from .llm.logging import LoggingProvider
        from .rate_limiter import get_config_with_overrides

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

    async def analyze_async(self, provider, rate_limiter, config, on_progress=None):
        results = await detect_dead_deps_async(provider, rate_limiter, config, on_progress)
        findings = [
            JunkFinding(
                source_path=v.manifest_path,
                name=v.package_name,
                kind="dependency",
                category="dead_dependency",
                line_start=v.line_number,
                line_end=None,
                confidence=v.confidence,
                reason=v.reason,
                remediation=v.remediation,
                original_purpose=f"dependency `{v.package_name}`",
                metadata={"usage_type": v.usage_type},
            )
            for v in results if v.is_dead
        ]
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=len(results),
            analyzer_name=self.name,
        )
