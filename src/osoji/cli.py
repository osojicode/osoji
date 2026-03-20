"""Click CLI for Osoji."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import click

from .audit import run_audit, format_audit_report, format_audit_json, format_audit_html, load_audit_result
from .config import Config
from .diff import run_diff, format_diff_report, format_diff_json
from .shadow import generate_shadow_docs_async, generate_shadow_docs, check_shadow_docs, mark_stale_docs, dry_run_shadow
from .stats import gather_stats, format_stats_report
from .observatory import write_observatory_bundle
from .hooks import install_hooks, uninstall_hooks
from .push import run_push
from .llm import provider_names
from .safety import check_staged_files, check_files as safety_check_files
from .safety.checker import format_check_result
from .safety.secrets import is_available as secrets_available
from .safety.paths import get_pattern_descriptions, PATTERNS, self_test as paths_self_test


_LLM_PROVIDER_CHOICE = click.Choice(provider_names(), case_sensitive=False)


@dataclass(frozen=True)
class CLIState:
    """Global CLI verbosity state."""

    verbose: bool = False
    quiet: bool = False


def _build_llm_config(
    path: Path,
    *,
    force: bool = False,
    no_gitignore: bool = False,
    provider: str | None = None,
    model: str | None = None,
    verbose: bool = False,
    quiet: bool = False,
) -> Config:
    return Config(
        root_path=path.resolve(),
        force=force,
        respect_gitignore=not no_gitignore,
        provider=provider,
        model=model,
        verbose=verbose,
        quiet=quiet,
    )


def _cli_state(ctx: click.Context) -> CLIState:
    """Return the inherited CLI state for the current command."""

    state = ctx.find_object(CLIState)
    return state if state is not None else CLIState()


def _emit_config_banner(config: Config) -> None:
    """Print config provenance for LLM-backed commands."""

    if config.quiet:
        return
    click.echo(config.format_resolution_banner(), err=True)


@click.group()
@click.version_option(package_name="osojicode")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option("--quiet", "-q", is_flag=True, help="Suppress nonessential diagnostic output")
@click.pass_context
def main(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """Osoji - Shadow Documentation Engine.

    Generate semantically dense documentation summaries optimized for AI agents.
    """
    if verbose and quiet:
        raise click.UsageError("Cannot use --verbose and --quiet together.")
    ctx.obj = CLIState(verbose=verbose, quiet=quiet)


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--force", "-f", is_flag=True, help="Regenerate all files, ignoring cached hashes")
@click.option("--dry-run", is_flag=True, help="Show what would be processed without making LLM calls")
@click.option("--provider", type=_LLM_PROVIDER_CHOICE, help="LLM provider to use")
@click.option("--model", help="Model ID to use for LLM requests")
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
@click.pass_context
def shadow(ctx: click.Context, path: Path, force: bool, dry_run: bool, provider: str | None, model: str | None, no_gitignore: bool) -> None:
    """Generate shadow documentation for a codebase.

    PATH is the root directory to process (defaults to current directory).
    """
    state = _cli_state(ctx)
    config = _build_llm_config(
        path,
        force=force,
        no_gitignore=no_gitignore,
        provider=provider,
        model=model,
        verbose=state.verbose,
        quiet=state.quiet,
    )
    _emit_config_banner(config)

    if dry_run:
        dry_run_shadow(config, verbose=state.verbose)
        return

    try:
        success = asyncio.run(generate_shadow_docs_async(config, verbose=state.verbose))
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    if not success:
        raise click.ClickException("Some files or directories failed to process (see errors above)")


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--dry-run", is_flag=True, help="Just print report, no file modifications")
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
def check(path: Path, dry_run: bool, no_gitignore: bool) -> None:
    """Check for stale or missing shadow documentation.

    By default, injects stale warnings into shadow docs and writes a
    staleness manifest.  Use --dry-run for a read-only report.

    PATH is the root directory to check (defaults to current directory).
    """
    config = _build_llm_config(
        path,
        no_gitignore=no_gitignore,
    )

    if dry_run:
        issues = check_shadow_docs(config)

        if not issues:
            click.echo("All shadow documentation is up to date.")
            return

        click.echo(f"Found {len(issues)} file(s) with issues:\n")

        status_colors = {"stale": "yellow", "missing": "red", "stale-impl": "cyan"}
        for file_path, status in issues:
            status_color = status_colors.get(status, "red")
            click.echo(f"  [{click.style(status, fg=status_color)}] {file_path}")

        click.echo(f"\nRun 'osoji shadow {path}' to update.")
        return

    result = mark_stale_docs(config)

    if not result.stale_files:
        click.echo("All shadow documentation is up to date.")
        return

    click.echo(f"Found {len(result.stale_files)} file(s) with issues:\n")

    status_colors = {"stale": "yellow", "missing": "red", "stale-impl": "cyan"}
    for file_path, status in result.stale_files:
        status_color = status_colors.get(status, "red")
        click.echo(f"  [{click.style(status, fg=status_color)}] {file_path}")

    click.echo(f"\nMarked {result.marked_count} shadow doc(s) with stale warnings.")
    click.echo(f"Manifest written to {config.staleness_manifest_path}")
    click.echo(f"\nRun 'osoji shadow {path}' to regenerate.")


@main.command()
@click.argument("base_ref", default="main")
@click.option("--update", is_flag=True, help="Regenerate stale shadow docs")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.option("--provider", type=_LLM_PROVIDER_CHOICE, help="LLM provider to use for shadow regeneration")
@click.option("--model", help="Model ID to use for shadow regeneration")
@click.pass_context
def diff(ctx: click.Context, base_ref: str, update: bool, output_format: str, provider: str | None, model: str | None) -> None:
    """Show documentation impact of source changes.

    Compare current HEAD against BASE_REF (defaults to main) and report:
    - Stale or missing shadow documentation for changed source files
    - Documentation files that reference changed source files

    \b
    Examples:
        osoji diff                    # Compare against main
        osoji diff develop            # Compare against develop
        osoji diff HEAD~5             # Compare against 5 commits ago
        osoji diff main --update      # Also regenerate stale shadows
        osoji diff main --format json # Machine-readable output

    Exit codes: 0 = no issues, 1 = issues found
    """
    state = _cli_state(ctx)
    config = _build_llm_config(
        Path("."),
        provider=provider,
        model=model,
        verbose=state.verbose,
        quiet=state.quiet,
    )
    _emit_config_banner(config)

    try:
        report = run_diff(config, base_ref)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

    if not report.changed_source and not report.changed_docs:
        click.echo("No changes found.")
        return

    if update and report.stale_shadows:
        click.echo("Osoji: Regenerating stale shadow documentation...")
        try:
            success = generate_shadow_docs(config, verbose=state.verbose)
            if not success:
                raise click.ClickException("Some files or directories failed to process (see errors above)")
            # Re-run to get updated report
            report = run_diff(config, base_ref)
        except RuntimeError as e:
            raise click.ClickException(str(e)) from e

    if output_format == "json":
        click.echo(format_diff_json(report))
    else:
        click.echo(format_diff_report(report))

    if report.has_issues:
        raise SystemExit(1)


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--provider", type=_LLM_PROVIDER_CHOICE, help="LLM provider to use for token counting")
@click.option("--model", help="Model ID to use for provider-aware token counting")
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
@click.pass_context
def stats(ctx: click.Context, path: Path, provider: str | None, model: str | None, no_gitignore: bool) -> None:
    """Show token statistics for source files vs shadow docs.

    Compares token counts between source code and generated shadow documentation
    to measure compression efficiency.

    PATH is the root directory to analyze (defaults to current directory).
    """
    state = _cli_state(ctx)
    config = _build_llm_config(
        path,
        no_gitignore=no_gitignore,
        provider=provider,
        model=model,
        verbose=state.verbose,
        quiet=state.quiet,
    )
    _emit_config_banner(config)

    if not state.quiet:
        click.echo("Gathering token statistics...")
    project_stats = gather_stats(config)
    
    report = format_stats_report(project_stats, verbose=state.verbose)
    click.echo(report)


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--fix/--no-fix", default=True, help="Auto-fix shadow docs (default: yes)")
@click.option("--format", "output_format", type=click.Choice(["text", "json", "html"]), default="text", help="Output format")
@click.option("--dead-code", is_flag=True, help="Detect cross-file dead code (LLM calls for ambiguous candidates)")
@click.option("--dead-params", is_flag=True, help="Detect dead function parameters (LLM calls)")
@click.option("--dead-plumbing", is_flag=True, help="Detect unactuated config obligations (LLM calls)")
@click.option("--dead-deps", is_flag=True, help="Detect unused package dependencies (LLM calls)")
@click.option("--dead-cicd", is_flag=True, help="Detect stale CI/CD pipeline elements (LLM calls)")
@click.option("--orphaned-files", is_flag=True, help="Detect orphaned source files (LLM calls)")
@click.option("--junk", is_flag=True, help="Run all junk code analysis phases")
@click.option("--obligations", is_flag=True, help="Check cross-file string contracts (no LLM calls)")
@click.option("--doc-prompts", is_flag=True, help="Generate concept-centric coverage + writing prompts (LLM calls)")
@click.option("--provider", type=_LLM_PROVIDER_CHOICE, help="LLM provider to use")
@click.option("--model", help="Model ID to use for LLM requests")
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
@click.option("--full", is_flag=True, help="Run all optional audit phases")
@click.option("--force", "-f", is_flag=True, help="Regenerate all shadow docs and findings from scratch")
@click.pass_context
def audit(ctx: click.Context, path: Path, fix: bool, output_format: str, dead_code: bool, dead_params: bool, dead_plumbing: bool, dead_deps: bool, dead_cicd: bool, orphaned_files: bool, junk: bool, obligations: bool, doc_prompts: bool, provider: str | None, model: str | None, no_gitignore: bool, full: bool, force: bool) -> None:
    """Run documentation audit.

    Checks for:
    - Documentation classification and accuracy validation against shadow docs
    - Code debris (stale comments, dead code, misleading docstrings)
    - Stale or missing shadow documentation (auto-fixed by default)
    - Cross-file dead code detection (opt-in with --dead-code)
    - Unactuated config obligation detection (opt-in with --dead-plumbing)
    - Unused package dependency detection (opt-in with --dead-deps)
    - Stale CI/CD pipeline element detection (opt-in with --dead-cicd)
    - Orphaned source file detection (opt-in with --orphaned-files)
    - All junk analysis phases at once (opt-in with --junk)

    Each doc file is matched to relevant source code via explicit references
    and semantic topic matching, then classified and validated in a single pass.

    Exit codes: 0 = passed, 1 = errors found
    """
    if full:
        junk = True
        obligations = True
        doc_prompts = True
    state = _cli_state(ctx)
    config = _build_llm_config(
        path,
        force=force,
        no_gitignore=no_gitignore,
        provider=provider,
        model=model,
        verbose=state.verbose,
        quiet=state.quiet,
    )
    _emit_config_banner(config)

    try:
        result = run_audit(config, fix_shadow=fix, dead_code=dead_code, dead_params=dead_params, dead_plumbing=dead_plumbing, dead_deps=dead_deps, dead_cicd=dead_cicd, orphaned_files=orphaned_files, junk=junk, obligations=obligations, doc_prompts=doc_prompts, verbose=state.verbose)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

    if output_format == "json":
        click.echo(format_audit_json(result))
    elif output_format == "html":
        html_str = format_audit_html(result, config=config)
        out_path = config.analysis_root / "report.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_str, encoding="utf-8")
        click.echo(f"Report written to {out_path}")
    else:
        report = format_audit_report(result, verbose=state.verbose)
        click.echo(report)

    if not result.passed:
        raise SystemExit(1)


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--format", "output_format", type=click.Choice(["text", "json", "html"]), default="text", help="Output format")
@click.pass_context
def report(ctx: click.Context, path: Path, output_format: str) -> None:
    """Re-render the last audit result in a different format (no re-analysis).

    Loads the cached result from the most recent 'osoji audit' run and
    formats it as text, JSON, or HTML. No LLM calls are made.
    """
    state = _cli_state(ctx)
    config = Config(root_path=path.resolve(), verbose=state.verbose, quiet=state.quiet)
    try:
        result = load_audit_result(config)
    except FileNotFoundError:
        raise click.ClickException("No cached audit result. Run 'osoji audit' first.")

    if output_format == "json":
        click.echo(format_audit_json(result))
    elif output_format == "html":
        html_str = format_audit_html(result, config=config)
        out_path = config.analysis_root / "report.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_str, encoding="utf-8")
        click.echo(f"Report written to {out_path}")
    else:
        report_text = format_audit_report(result, verbose=state.verbose)
        click.echo(report_text)

    if not result.passed:
        raise SystemExit(1)


@main.command()
@click.option("--project", help="Project slug (default: from config or git remote)")
@click.option("--org", help="Organization slug (default: from config or git remote)")
@click.option("--token", help="API token (default: OSOJI_TOKEN env var)")
@click.option("--endpoint", help="API endpoint URL (default: OSOJI_ENDPOINT env var)")
@click.pass_context
def push(ctx: click.Context, project: str | None, org: str | None, token: str | None, endpoint: str | None) -> None:
    """Push observatory bundle to osoji-teams."""
    state = _cli_state(ctx)

    result = run_push(
        endpoint=endpoint,
        token=token,
        project=project,
        org=org,
        root_path=Path(".").resolve(),
        quiet=state.quiet,
    )

    if result.duplicate:
        click.echo(f"Bundle already pushed (duplicate). run_id: {result.run_id}")
    else:
        click.echo(f"Pushed successfully. run_id: {result.run_id}")
        if result.dashboard_url:
            click.echo(f"Dashboard: {result.dashboard_url}")


@main.command(name="export")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the observatory bundle to this file (defaults to .osoji/analysis/observatory.json).",
)
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
def export_bundle(path: Path, output: Path | None, no_gitignore: bool) -> None:
    """Export a stable, versioned observatory bundle for downstream consumers."""
    out_path = write_observatory_bundle(
        path,
        output_path=output,
        respect_gitignore=not no_gitignore,
    )
    click.echo(f"Observatory bundle written to {out_path}")


@main.group()
def hooks() -> None:
    """Manage git hooks for automatic shadow doc updates."""
    pass


@hooks.command("install")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing hooks")
@click.option("--pre-commit/--no-pre-commit", default=True, help="Install pre-commit hook (default: yes)")
@click.option("--pre-push/--no-pre-push", default=True, help="Install pre-push hook (default: yes)")
@click.option("--post-commit/--no-post-commit", default=False, help="Install post-commit hook (default: no)")
def hooks_install(
    path: Path,
    force: bool,
    pre_commit: bool,
    pre_push: bool,
    post_commit: bool,
) -> None:
    """Install git hooks for automatic shadow doc updates.

    Hooks installed:
    
    \b
    - pre-commit: Updates shadow docs for staged files before commit
    - pre-push: Warns about stale shadow docs before push
    - post-commit (optional): Reminds to update after commit
    """
    results = install_hooks(
        repo_path=path.resolve(),
        pre_commit=pre_commit,
        post_commit=post_commit,
        pre_push=pre_push,
        force=force,
    )

    all_success = True
    for hook_name, success, message in results:
        if success:
            click.echo(f"  [ok] {message}")
        else:
            click.echo(f"  [FAIL] {message}")
            all_success = False

    if all_success:
        click.echo("\nHooks installed successfully.")
        click.echo("Shadow docs will be updated automatically on commit.")
    else:
        click.echo("\nSome hooks could not be installed.")


@hooks.command("uninstall")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
def hooks_uninstall(path: Path) -> None:
    """Remove osoji git hooks."""
    results = uninstall_hooks(repo_path=path.resolve())

    for hook_name, success, message in results:
        if success:
            click.echo(f"  [ok] {message}")
        else:
            click.echo(f"  [FAIL] {message}")


@main.group()
def safety() -> None:
    """Pre-commit safety checks for personal paths and secrets."""
    pass


@safety.command("check")
@click.argument("files", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.pass_context
def safety_check(ctx: click.Context, files: tuple[Path, ...]) -> None:
    """Check files for personal paths and secrets.

    If no FILES specified, checks all staged git files.

    \b
    Examples:
        osoji safety check              # Check staged files
        osoji safety check src/*.py     # Check specific files
    """
    if files:
        result = safety_check_files([f.resolve() for f in files])
    else:
        result = check_staged_files()

    report = format_check_result(result, verbose=_cli_state(ctx).verbose)
    click.echo(report)

    if not result.passed:
        raise SystemExit(1)


@safety.command("self-test")
def safety_self_test() -> None:
    """Verify the safety module doesn't contain real personal paths.

    Scans the osoji package itself to ensure no personal paths
    have been accidentally committed.

    Note: The paths.py file is handled specially since it contains
    example paths in documentation that are not real personal paths.
    """
    import osoji

    package_dir = Path(osoji.__file__).parent

    click.echo(f"Scanning {package_dir}...")

    # Get all Python files in the package, excluding paths.py which has its own self-test
    # (paths.py contains example paths in documentation)
    paths_module = package_dir / "safety" / "paths.py"
    py_files = [f for f in package_dir.rglob("*.py") if f != paths_module]
    result = safety_check_files(py_files)

    # Run the paths module self-test (it has special filtering for doc examples)
    paths_passed, paths_findings = paths_self_test()

    report = format_check_result(result, verbose=True)
    click.echo(report)

    if not paths_passed:
        click.echo("\npaths.py self-test found issues:")
        for finding in paths_findings:
            click.echo(f"  Line {finding.line_number}: {finding.match}")

    if result.passed and paths_passed:
        click.echo("\nSelf-test passed: No personal paths found in osoji package.")
    else:
        click.echo("\nSelf-test FAILED: Personal paths found in osoji package!")
        raise SystemExit(1)


@safety.command("patterns")
def safety_patterns() -> None:
    """Show the path patterns being checked.

    Lists all regex patterns used to detect personal paths,
    with descriptions and examples.
    """
    click.echo("Personal Path Patterns")
    click.echo("=" * 50)
    click.echo("")

    descriptions = get_pattern_descriptions()

    for name, pattern in PATTERNS.items():
        desc = descriptions.get(name, "No description")
        click.echo(f"[{name}]")
        click.echo(f"  Description: {desc}")
        click.echo(f"  Regex: {pattern.pattern}")
        click.echo("")

    click.echo("-" * 50)
    click.echo(f"Total: {len(PATTERNS)} patterns")

    if secrets_available():
        click.echo("\ndetect-secrets: installed (secrets will be checked)")
    else:
        click.echo("\ndetect-secrets: not installed")
        click.echo("  Install with: pip install 'osoji[safety]'")


@main.group("config")
def config_cmd() -> None:
    """Inspect resolved Osoji configuration."""
    pass


@config_cmd.command("show")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.pass_context
def config_show(ctx: click.Context, path: Path) -> None:
    """Show the effective model policy for a project root."""

    state = _cli_state(ctx)
    config = _build_llm_config(path, verbose=state.verbose, quiet=state.quiet)
    click.echo(config.format_resolution_banner())


@main.group()
def skills() -> None:
    """AI agent skill prompts bundled with osoji."""
    pass


@skills.command("list")
def skills_list() -> None:
    """List available skill prompts."""
    from .skills import list_skills as _list_skills

    entries = _list_skills()
    if not entries:
        click.echo("No bundled skills found.")
        return
    max_name = max(len(e["name"]) for e in entries)
    for e in entries:
        click.echo(f"  {e['name']:<{max_name}}  {e['description']}")


@skills.command("show")
@click.argument("name")
def skills_show(name: str) -> None:
    """Print the full content of a skill prompt."""
    from .skills import get_skill

    content = get_skill(name)
    if content is None:
        from .skills import list_skills as _list_skills
        names = [e["name"] for e in _list_skills()]
        raise click.ClickException(
            f"Unknown skill '{name}'. Available: {', '.join(names)}"
        )
    click.echo(content)


if __name__ == "__main__":
    main()
