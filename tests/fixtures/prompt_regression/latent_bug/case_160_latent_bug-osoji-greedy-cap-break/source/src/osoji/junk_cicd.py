"""Dead CI/CD detection via pipeline file parsing and path reference checking."""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import ANTHROPIC_MODEL_SMALL, Config
from .evidence_builders import BuildContext, _scanner_meta
from .facts import FactsDB
from .findings import Finding
from .findings_adapter import finding_from_cicd_candidate
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult
from .junk_triage import build_junk_claims, decide_junk_claims
from .llm.base import LLMProvider
from .llm.runtime import create_runtime
from .llm.types import Message, MessageRole, CompletionOptions
from .tools import get_extract_cicd_elements_tool_definitions
from .walker import list_repo_files



@dataclass
class CICDElement:
    """A parsed element from a CI/CD file."""

    cicd_file: str            # e.g. ".github/workflows/ci.yml"
    element_type: str         # "workflow_job", "makefile_target", "gitlab_job"
    element_name: str
    line_start: int
    line_end: int
    referenced_paths: list[str] = field(default_factory=list)
    referenced_commands: list[str] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)


@dataclass
class CICDCandidate:
    """A CI/CD element that may be dead."""

    cicd_file: str
    element_name: str
    element_type: str
    line_start: int
    line_end: int
    missing_paths: list[str]
    element_content: str      # raw text of the element for LLM context
    full_file_content: str


# --- CI/CD file discovery ---

def discover_cicd_files(config: Config) -> list[tuple[Path, str]]:
    """Discover CI/CD configuration files via direct filesystem scan.

    .github is in DEFAULT_IGNORE_PATTERNS, so we use Path.iterdir()
    instead of list_repo_files().

    Returns list of (absolute_path, cicd_type).
    """
    root = config.root_path
    found: list[tuple[Path, str]] = []

    # .github/workflows/*.yml and *.yaml
    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.is_dir():
        for child in workflows_dir.iterdir():
            if child.is_file() and child.suffix in (".yml", ".yaml"):
                found.append((child, "github_workflow"))

    # Makefile variants
    for name in ("Makefile", "GNUmakefile", "makefile"):
        p = root / name
        if p.is_file():
            found.append((p, "makefile"))

    # GitLab CI
    p = root / ".gitlab-ci.yml"
    if p.is_file():
        found.append((p, "gitlab_ci"))

    # Jenkinsfile
    p = root / "Jenkinsfile"
    if p.is_file():
        found.append((p, "jenkinsfile"))

    # CircleCI
    p = root / ".circleci" / "config.yml"
    if p.is_file():
        found.append((p, "circleci"))

    # Azure Pipelines
    p = root / "azure-pipelines.yml"
    if p.is_file():
        found.append((p, "azure_pipelines"))

    # Travis CI
    p = root / ".travis.yml"
    if p.is_file():
        found.append((p, "travis_ci"))

    return found


# --- CI/CD parsers ---

def _parse_github_workflow(content: str, path: str) -> list[CICDElement]:
    """Parse a GitHub Actions workflow file.

    Regex-based extraction of jobs and their run/uses steps.
    """
    elements: list[CICDElement] = []
    lines = content.splitlines()

    # Find jobs: section
    jobs_line = None
    for i, line in enumerate(lines):
        if re.match(r"^jobs:\s*$", line):
            jobs_line = i
            break

    if jobs_line is None:
        return []

    # Extract job names: lines at exactly 2 spaces of indent after jobs:
    job_re = re.compile(r"^  ([a-zA-Z_][\w-]*):\s*$")
    jobs: list[tuple[str, int, int]] = []  # (name, start, end)

    for i in range(jobs_line + 1, len(lines)):
        m = job_re.match(lines[i])
        if m:
            if jobs:
                jobs[-1] = (jobs[-1][0], jobs[-1][1], i - 1)
            jobs.append((m.group(1), i, len(lines) - 1))
        # If we hit a line at indent 0 that isn't empty/comment, jobs section is over
        elif lines[i].strip() and not lines[i].startswith(" ") and not lines[i].startswith("#"):
            if jobs:
                jobs[-1] = (jobs[-1][0], jobs[-1][1], i - 1)
            break

    for job_name, start, end in jobs:
        job_lines = lines[start:end + 1]

        # Extract referenced paths and commands from run: and uses: lines
        paths: list[str] = []
        commands: list[str] = []

        in_run_block = False
        run_block_indent = 0
        for jline in job_lines:
            stripped = jline.strip()

            # Handle "- run:" or "run:" (with or without list marker)
            run_match = re.match(r"^-?\s*run:\s*(.*)", stripped)
            if run_match:
                rest = run_match.group(1).strip().strip("|")
                if rest:
                    commands.append(rest)
                    paths.extend(_extract_paths_from_command(rest))
                    in_run_block = False
                else:
                    in_run_block = True
                    # Determine indent level of the run: line
                    run_block_indent = len(jline) - len(jline.lstrip())
                continue

            if in_run_block:
                line_indent = len(jline) - len(jline.lstrip())
                if stripped and line_indent > run_block_indent:
                    commands.append(stripped)
                    paths.extend(_extract_paths_from_command(stripped))
                elif not stripped:
                    continue
                else:
                    in_run_block = False

            # Handle "- uses:" or "uses:"
            uses_match = re.match(r"^-?\s*uses:\s*(.*)", stripped)
            if uses_match:
                commands.append(uses_match.group(1).strip())

        elements.append(CICDElement(
            cicd_file=path,
            element_type="workflow_job",
            element_name=job_name,
            line_start=start + 1,  # 1-indexed
            line_end=end + 1,
            referenced_paths=paths,
            referenced_commands=commands,
        ))

    return elements


def _parse_makefile(content: str, path: str) -> list[CICDElement]:
    """Parse a Makefile to extract targets and recipe commands."""
    elements: list[CICDElement] = []
    lines = content.splitlines()

    target_re = re.compile(r"^([a-zA-Z_][\w.\-]*)(?:\s+[a-zA-Z_][\w.\-]*)?\s*:(?!=)")
    current_target: str | None = None
    current_start = 0
    current_paths: list[str] = []
    current_commands: list[str] = []

    def _flush():
        if current_target is not None:
            elements.append(CICDElement(
                cicd_file=path,
                element_type="makefile_target",
                element_name=current_target,
                line_start=current_start + 1,
                line_end=len(lines),
                referenced_paths=current_paths[:],
                referenced_commands=current_commands[:],
            ))

    for i, line in enumerate(lines):
        m = target_re.match(line)
        if m:
            _flush()
            current_target = m.group(1)
            current_start = i
            current_paths = []
            current_commands = []
            # Update end of previous element
            if elements:
                elements[-1].line_end = i
        elif line.startswith("\t") and current_target is not None:
            cmd = line[1:].strip()
            if cmd and not cmd.startswith("#"):
                current_commands.append(cmd)
                current_paths.extend(_extract_paths_from_command(cmd))

    _flush()

    return elements


def _parse_gitlab_ci(content: str, path: str) -> list[CICDElement]:
    """Parse a GitLab CI file to extract jobs."""
    elements: list[CICDElement] = []
    lines = content.splitlines()

    reserved_keys = {
        "stages", "variables", "default", "include", "image", "services",
        "before_script", "after_script", "cache", "workflow",
        "pages", "trigger", "resource_group", "retry", "timeout",
        "interruptible", "artifacts", "dependencies", "needs",
        "environment", "release", "coverage", "parallel", "tags",
        "only", "except", "rules", "when", "allow_failure",
    }

    # Find top-level keys (not indented)
    job_re = re.compile(r"^([a-zA-Z_][\w.\-/]*):\s*")
    jobs: list[tuple[str, int]] = []

    for i, line in enumerate(lines):
        m = job_re.match(line)
        if m:
            key = m.group(1)
            if key in reserved_keys:
                continue
            jobs.append((key, i))

    for idx, (job_name, start) in enumerate(jobs):
        end = jobs[idx + 1][1] - 1 if idx + 1 < len(jobs) else len(lines) - 1
        job_lines = lines[start:end + 1]

        paths: list[str] = []
        commands: list[str] = []
        in_script = False

        for jline in job_lines:
            stripped = jline.strip()
            if stripped.startswith("script:"):
                in_script = True
                continue
            if in_script:
                if stripped.startswith("- "):
                    cmd = stripped[2:].strip()
                    commands.append(cmd)
                    paths.extend(_extract_paths_from_command(cmd))
                elif stripped and not stripped.startswith("#") and not jline.startswith("  "):
                    in_script = False

        elements.append(CICDElement(
            cicd_file=path,
            element_type="gitlab_job",
            element_name=job_name,
            line_start=start + 1,
            line_end=end + 1,
            referenced_paths=paths,
            referenced_commands=commands,
        ))

    return elements


_EXTRACT_CICD_SYSTEM_PROMPT = """You are a CI/CD configuration parser. Extract all discrete pipeline elements from the given configuration file.

For each element (job, stage, target, step, pipeline), identify:
1. Its name and type
2. The line range it occupies in the file
3. Any file paths it references (scripts, directories, config files)
4. Any commands it runs

Be thorough — extract ALL elements. For line numbers, count from line 1."""


async def _parse_cicd_via_llm(
    provider: LLMProvider,
    content: str,
    path: str,
    cicd_type: str,
    config: Config | None = None,
) -> tuple[list[CICDElement], int, int]:
    """Parse a CI/CD file using the small LLM model when no regex parser is available.

    Returns (elements, input_tokens, output_tokens).
    """
    lines = [
        f"## CI/CD file: `{path}` (type: {cicd_type})\n",
        f"```\n{content[:50000]}\n```\n",
        "Extract ALL pipeline elements from this file.",
    ]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(lines))],
        system=_EXTRACT_CICD_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("small") if config is not None else ANTHROPIC_MODEL_SMALL,
            max_tokens=4096,
            reservation_key="junk_cicd.extract_elements",
            tools=get_extract_cicd_elements_tool_definitions(),
            tool_choice={"type": "tool", "name": "extract_cicd_elements"},
        ),
    )

    elements: list[CICDElement] = []
    for tc in result.tool_calls:
        if tc.name == "extract_cicd_elements":
            for elem in tc.input.get("elements", []):
                elements.append(CICDElement(
                    cicd_file=path,
                    element_type=elem.get("element_type", cicd_type + "_job"),
                    element_name=elem.get("element_name", "unknown"),
                    line_start=elem.get("line_start", 1),
                    line_end=elem.get("line_end", 1),
                    referenced_paths=elem.get("referenced_paths", []),
                    referenced_commands=elem.get("referenced_commands", []),
                ))

    return elements, result.input_tokens, result.output_tokens


# --- Path extraction ---

# Common commands that are not file paths
_COMMON_COMMANDS = {
    "echo", "cd", "mkdir", "rm", "cp", "mv", "ls", "cat", "grep", "sed",
    "awk", "find", "chmod", "chown", "export", "source", "eval", "exec",
    "if", "then", "else", "fi", "for", "do", "done", "while", "case",
    "esac", "true", "false", "exit", "return", "set", "unset", "test",
    "pip", "pip3", "python", "python3", "node", "npm", "npx", "yarn",
    "pnpm", "cargo", "go", "make", "git", "docker", "kubectl",
    "curl", "wget", "tar", "unzip", "gzip",
    "sudo", "env", "bash", "sh", "zsh",
}


def _extract_paths_from_command(command: str) -> list[str]:
    """Extract file path-like tokens from a shell command."""
    paths: list[str] = []

    # Remove shell variable references and backtick/$(cmd) substitutions
    cleaned = re.sub(r"\$\{[^}]*\}", "", command)
    cleaned = re.sub(r"\$\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"`[^`]*`", "", cleaned)
    cleaned = re.sub(r"\$\w+", "", cleaned)

    # Tokenize by whitespace
    tokens = cleaned.split()

    for token in tokens:
        # Strip quotes
        token = token.strip("'\"")

        # Skip flags
        if token.startswith("-"):
            continue

        # Skip URLs
        if re.match(r"https?://", token):
            continue

        # Skip empty or very short tokens
        if len(token) < 2:
            continue

        # Skip common commands
        if token.lower() in _COMMON_COMMANDS:
            continue

        # Skip tokens that look like options or environment variables
        if "=" in token and not "/" in token:
            continue

        # Include tokens that look like file paths
        if "/" in token or "." in token:
            # Must contain at least one path-like character
            if re.search(r"[a-zA-Z]", token):
                paths.append(token)

    return paths


# --- Path reference checking ---

def _check_path_references(
    config: Config,
    elements: list[CICDElement],
) -> list[CICDElement]:
    """Check which referenced paths actually exist in the repo.

    Populates missing_paths on each element.
    """
    # Build set of all known files: repo files + .github/ contents
    all_paths, _ = list_repo_files(config)
    known_files: set[str] = set()

    for p in all_paths:
        if not p.is_absolute():
            p = config.root_path / p
        rel = str(p.relative_to(config.root_path)).replace("\\", "/")
        known_files.add(rel)

    # Also scan .github/ since it's in ignore patterns
    github_dir = config.root_path / ".github"
    if github_dir.is_dir():
        for child in github_dir.rglob("*"):
            if child.is_file():
                rel = str(child.relative_to(config.root_path)).replace("\\", "/")
                known_files.add(rel)

    # Also add directories
    known_dirs: set[str] = set()
    for f in known_files:
        parts = f.split("/")
        for i in range(1, len(parts)):
            known_dirs.add("/".join(parts[:i]))

    for element in elements:
        element.missing_paths = []
        for ref_path in element.referenced_paths:
            # Normalize
            normalized = ref_path.removeprefix("./").replace("\\", "/")
            if not normalized:
                continue
            # Check if path or any parent dir exists
            if normalized not in known_files and normalized not in known_dirs:
                # Also check glob-style (e.g. src/**/*.py matches if src/ exists)
                base = normalized.split("*")[0].rstrip("/")
                if base and base not in known_files and base not in known_dirs:
                    element.missing_paths.append(ref_path)

    return elements


def _build_candidates(
    elements: list[CICDElement],
    file_contents: dict[str, str],
) -> list[CICDCandidate]:
    """Filter to elements with missing paths and build candidates."""
    candidates: list[CICDCandidate] = []

    for elem in elements:
        if not elem.missing_paths:
            continue

        full_content = file_contents.get(elem.cicd_file, "")
        lines = full_content.splitlines()
        elem_lines = lines[elem.line_start - 1:elem.line_end]
        elem_content = "\n".join(elem_lines)

        candidates.append(CICDCandidate(
            cicd_file=elem.cicd_file,
            element_name=elem.element_name,
            element_type=elem.element_type,
            line_start=elem.line_start,
            line_end=elem.line_end,
            missing_paths=elem.missing_paths,
            element_content=elem_content,
            full_file_content=full_content,
        ))

    return candidates


# --- Full pipeline ---

_CICD_PARSERS: dict[str, Callable] = {
    "github_workflow": _parse_github_workflow,
    "makefile": _parse_makefile,
    "gitlab_ci": _parse_gitlab_ci,
}


async def detect_dead_cicd_async(
    provider: LLMProvider,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
    *,
    cicd_files: list[tuple[Path, str]] | None = None,
) -> tuple[list[Finding], int]:
    """Detect stale CI/CD pipeline elements through the unified pipeline.

    Elements whose referenced paths are missing become reachability Findings; the
    Claim Builder gathers repo mentions of the element name and script names, and
    Triage judges external-target / dynamic-discovery / phony-target liveness
    (missing paths are the primary but not dispositive signal).

    Returns ``(decided Findings — all verdicts; callers keep ``confirmed`` —,
    total candidate count)``.
    """
    if cicd_files is None:
        cicd_files = discover_cicd_files(config)
    if not cicd_files:
        print("  [skip] No CI/CD configuration files found.", flush=True)
        return [], 0

    print(f"  Found {len(cicd_files)} CI/CD file(s)", flush=True)

    # Parse all CI/CD files
    all_elements: list[CICDElement] = []
    file_contents: dict[str, str] = {}

    for abs_path, cicd_type in cicd_files:
        try:
            content = abs_path.read_text(errors="ignore")
        except OSError:
            continue

        rel_path = str(abs_path.relative_to(config.root_path)).replace("\\", "/")
        file_contents[rel_path] = content

        parser = _CICD_PARSERS.get(cicd_type)
        if parser:
            elements = parser(content, rel_path)
            all_elements.extend(elements)
        else:
            # Use small model for unsupported CI/CD systems
            try:
                parsed_elements, _in_tok, _out_tok = await _parse_cicd_via_llm(
                    provider, content, rel_path, cicd_type, config,
                )
                all_elements.extend(parsed_elements)
                if parsed_elements:
                    print(f"  LLM parsed {len(parsed_elements)} element(s) from {rel_path}", flush=True)
            except Exception as e:
                print(f"  [warn] LLM CI/CD parsing failed for {rel_path}: {e}", flush=True)

    if not all_elements:
        print("  No CI/CD elements found to analyze.", flush=True)
        return [], 0

    print(f"  Found {len(all_elements)} CI/CD element(s)", flush=True)

    # Check path references
    _check_path_references(config, all_elements)

    # Build candidates (elements with missing paths)
    candidates = _build_candidates(all_elements, file_contents)

    print(
        f"  {len(candidates)} element(s) with missing path references for LLM verification "
        f"(from {len(all_elements)} total elements)",
        flush=True,
    )

    total_candidates = len(candidates)

    if not candidates:
        return [], 0

    # Build claims and decide through unified Triage
    findings = [finding_from_cicd_candidate(c) for c in candidates]
    ctx = BuildContext(config, facts_db=FactsDB(config))
    claims = build_junk_claims(findings, ctx)
    decided, _in_tok, _out_tok = await decide_junk_claims(
        claims, config, provider, on_progress=on_progress
    )
    return decided, total_candidates


class DeadCICDAnalyzer(JunkAnalyzer):
    """Junk analyzer that detects stale CI/CD pipeline elements."""

    @property
    def name(self) -> str:
        return "dead_cicd"

    @property
    def description(self) -> str:
        return "Detect stale CI/CD pipeline elements"

    @property
    def cli_flag(self) -> str:
        return "dead-cicd"

    def analyze(self, config):
        """Sync wrapper — skip symbols-dir check (CI/CD doesn't need symbols)."""
        cicd_files = discover_cicd_files(config)
        if not cicd_files:
            print("  [skip] No CI/CD configuration files found.", flush=True)
            return JunkAnalysisResult(findings=[], total_candidates=0, analyzer_name=self.name)

        async def _run() -> JunkAnalysisResult:
            logging_provider, _ = create_runtime(config)
            try:
                return await self.analyze_async(
                    logging_provider, config, None, cicd_files=cicd_files
                )
            finally:
                await logging_provider.close()

        return asyncio.run(_run())

    async def analyze_async(self, provider, config, on_progress=None, cicd_files=None):
        decided, total_candidates = await detect_dead_cicd_async(
            provider, config, on_progress, cicd_files=cicd_files
        )
        findings = []
        for f in decided:
            if f.verdict != "confirmed":
                continue
            meta = _scanner_meta(f)
            element_name = meta.get("element_name", f.symbol or "")
            element_type = meta.get("element_type", f.contract_source or "element")
            findings.append(JunkFinding(
                source_path=f.path,
                name=element_name,
                kind=element_type,
                category="dead_cicd",
                line_start=f.line_start or 1,
                line_end=f.line_end,
                confidence=f.confidence if f.confidence is not None else 0.0,
                reason=f.triage_reasoning or "",
                remediation=f.suggested_fix or f"Remove {element_type} `{element_name}`",
                original_purpose=f"{element_type} `{element_name}`",
                confidence_source="llm_inferred",
                finding_id=f.id,
                verdict=f.verdict,
            ))
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=total_candidates,
            analyzer_name=self.name,
        )
