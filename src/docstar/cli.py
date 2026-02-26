"""Click CLI for Docstar."""

import asyncio
from pathlib import Path

import click

from .audit import run_audit, format_audit_report, format_audit_json
from .config import Config
from .diff import run_diff, format_diff_report, format_diff_json
from .shadow import generate_shadow_docs_async, generate_shadow_docs, check_shadow_docs, dry_run_shadow
from .stats import gather_stats, format_stats_report
from .hooks import install_hooks, uninstall_hooks
from .safety import check_staged_files, check_files as safety_check_files
from .safety.checker import format_check_result
from .safety.secrets import is_available as secrets_available
from .safety.paths import get_pattern_descriptions, PATTERNS, self_test as paths_self_test


@click.group()
@click.version_option()
def main() -> None:
    """Docstar - Shadow Documentation Engine.

    Generate semantically dense documentation summaries optimized for AI agents.
    """
    pass


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--force", "-f", is_flag=True, help="Regenerate all files, ignoring cached hashes")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
@click.option("--dry-run", is_flag=True, help="Show what would be processed without making LLM calls")
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
def shadow(path: Path, force: bool, verbose: bool, dry_run: bool, no_gitignore: bool) -> None:
    """Generate shadow documentation for a codebase.

    PATH is the root directory to process (defaults to current directory).
    """
    config = Config(
        root_path=path.resolve(),
        force=force,
        respect_gitignore=not no_gitignore,
    )

    if dry_run:
        dry_run_shadow(config, verbose=verbose)
        return

    try:
        success = asyncio.run(generate_shadow_docs_async(config, verbose=verbose))
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    if not success:
        raise click.ClickException("Some files or directories failed to process (see errors above)")


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
def check(path: Path, no_gitignore: bool) -> None:
    """Check for stale or missing shadow documentation.

    PATH is the root directory to check (defaults to current directory).
    """
    config = Config(root_path=path.resolve(), respect_gitignore=not no_gitignore)

    issues = check_shadow_docs(config)

    if not issues:
        click.echo("All shadow documentation is up to date.")
        return

    click.echo(f"Found {len(issues)} file(s) with issues:\n")

    for file_path, status in issues:
        status_color = "yellow" if status == "stale" else "red"
        click.echo(f"  [{click.style(status, fg=status_color)}] {file_path}")

    click.echo(f"\nRun 'docstar shadow {path}' to update.")


@main.command()
@click.argument("base_ref", default="main")
@click.option("--update", is_flag=True, help="Regenerate stale shadow docs")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
def diff(base_ref: str, update: bool, output_format: str) -> None:
    """Show documentation impact of source changes.

    Compare current HEAD against BASE_REF (defaults to main) and report:
    - Stale or missing shadow documentation for changed source files
    - Documentation files that reference changed source files

    \b
    Examples:
        docstar diff                    # Compare against main
        docstar diff develop            # Compare against develop
        docstar diff HEAD~5             # Compare against 5 commits ago
        docstar diff main --update      # Also regenerate stale shadows
        docstar diff main --format json # Machine-readable output

    Exit codes: 0 = no issues, 1 = issues found
    """
    config = Config(root_path=Path(".").resolve())

    try:
        report = run_diff(config, base_ref)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

    if not report.changed_source and not report.changed_docs:
        click.echo("No changes found.")
        return

    if update and report.stale_shadows:
        click.echo("Docstar: Regenerating stale shadow documentation...")
        try:
            success = generate_shadow_docs(config)
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
@click.option("--verbose", "-v", is_flag=True, help="Show per-file breakdown")
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
def stats(path: Path, verbose: bool, no_gitignore: bool) -> None:
    """Show token statistics for source files vs shadow docs.

    Compares token counts between source code and generated shadow documentation
    to measure compression efficiency.

    PATH is the root directory to analyze (defaults to current directory).
    """
    config = Config(root_path=path.resolve(), respect_gitignore=not no_gitignore)

    click.echo("Gathering token statistics...")
    project_stats = gather_stats(config)
    
    report = format_stats_report(project_stats, verbose=verbose)
    click.echo(report)


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--fix/--no-fix", default=True, help="Auto-fix shadow docs (default: yes)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.option("--dead-code", is_flag=True, help="Detect cross-file dead code (LLM calls for ambiguous candidates)")
@click.option("--dead-plumbing", is_flag=True, help="Detect unactuated config obligations (LLM calls)")
@click.option("--dead-deps", is_flag=True, help="Detect unused package dependencies (LLM calls)")
@click.option("--dead-cicd", is_flag=True, help="Detect stale CI/CD pipeline elements (LLM calls)")
@click.option("--orphaned-files", is_flag=True, help="Detect orphaned source files (LLM calls)")
@click.option("--junk", is_flag=True, help="Run all junk code analysis phases")
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
@click.option("--full", is_flag=True, help="Run all optional audit phases")
def audit(path: Path, fix: bool, verbose: bool, output_format: str, dead_code: bool, dead_plumbing: bool, dead_deps: bool, dead_cicd: bool, orphaned_files: bool, junk: bool, no_gitignore: bool, full: bool) -> None:
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
    config = Config(root_path=path.resolve(), respect_gitignore=not no_gitignore)

    try:
        result = run_audit(config, fix_shadow=fix, dead_code=dead_code, dead_plumbing=dead_plumbing, dead_deps=dead_deps, dead_cicd=dead_cicd, orphaned_files=orphaned_files, junk=junk, verbose=verbose)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

    if output_format == "json":
        click.echo(format_audit_json(result))
    else:
        report = format_audit_report(result, verbose=verbose)
        click.echo(report)

    if not result.passed:
        raise SystemExit(1)


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
            click.echo(f"  ✓ {message}")
        else:
            click.echo(f"  ✗ {message}")
            all_success = False

    if all_success:
        click.echo("\nHooks installed successfully.")
        click.echo("Shadow docs will be updated automatically on commit.")
    else:
        click.echo("\nSome hooks could not be installed.")


@hooks.command("uninstall")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
def hooks_uninstall(path: Path) -> None:
    """Remove docstar git hooks."""
    results = uninstall_hooks(repo_path=path.resolve())

    for hook_name, success, message in results:
        if success:
            click.echo(f"  ✓ {message}")
        else:
            click.echo(f"  ✗ {message}")


@main.group()
def safety() -> None:
    """Pre-commit safety checks for personal paths and secrets."""
    pass


@safety.command("check")
@click.argument("files", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def safety_check(files: tuple[Path, ...], verbose: bool) -> None:
    """Check files for personal paths and secrets.

    If no FILES specified, checks all staged git files.

    \b
    Examples:
        docstar safety check              # Check staged files
        docstar safety check src/*.py     # Check specific files
    """
    if files:
        result = safety_check_files([f.resolve() for f in files])
    else:
        result = check_staged_files()

    report = format_check_result(result, verbose=verbose)
    click.echo(report)

    if not result.passed:
        raise SystemExit(1)


@safety.command("self-test")
def safety_self_test() -> None:
    """Verify the safety module doesn't contain real personal paths.

    Scans the docstar package itself to ensure no personal paths
    have been accidentally committed.

    Note: The paths.py file is handled specially since it contains
    example paths in documentation that are not real personal paths.
    """
    import docstar

    package_dir = Path(docstar.__file__).parent

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
        click.echo("\nSelf-test passed: No personal paths found in docstar package.")
    else:
        click.echo("\nSelf-test FAILED: Personal paths found in docstar package!")
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
        click.echo("  Install with: pip install 'docstar[safety]'")


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--port", "-p", default=8765, type=int, help="Port to serve on")
@click.option("--no-open", is_flag=True, help="Don't auto-open browser")
@click.option("--no-gitignore", is_flag=True, help="Don't use .gitignore for file filtering")
def viz(path: Path, port: int, no_open: bool, no_gitignore: bool) -> None:
    """Open interactive codebase health visualization in browser."""
    config = Config(root_path=path.resolve(), respect_gitignore=not no_gitignore)
    from .viz import serve_viz
    serve_viz(config, port=port, open_browser=not no_open)


if __name__ == "__main__":
    main()
