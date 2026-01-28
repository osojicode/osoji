"""Click CLI for Docstar."""

from pathlib import Path

import click

from .audit import run_audit, format_audit_report
from .config import Config
from .shadow import generate_shadow_docs, check_shadow_docs
from .stats import gather_stats, format_stats_report, HAS_TIKTOKEN
from .hooks import install_hooks, uninstall_hooks


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
def shadow(path: Path, force: bool) -> None:
    """Generate shadow documentation for a codebase.

    PATH is the root directory to process (defaults to current directory).
    """
    config = Config(
        root_path=path.resolve(),
        force=force,
    )

    try:
        generate_shadow_docs(config)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
def check(path: Path) -> None:
    """Check for stale or missing shadow documentation.

    PATH is the root directory to check (defaults to current directory).
    """
    config = Config(root_path=path.resolve())

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
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--verbose", "-v", is_flag=True, help="Show per-file breakdown")
def stats(path: Path, verbose: bool) -> None:
    """Show token statistics for source files vs shadow docs.

    Compares token counts between source code and generated shadow documentation
    to measure compression efficiency.

    PATH is the root directory to analyze (defaults to current directory).
    """
    config = Config(root_path=path.resolve())

    click.echo("Gathering token statistics...")
    project_stats = gather_stats(config)
    
    report = format_stats_report(project_stats, verbose=verbose)
    click.echo(report)


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--fix/--no-fix", default=True, help="Auto-fix shadow docs (default: yes)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def audit(path: Path, fix: bool, verbose: bool) -> None:
    """Run documentation audit.

    Checks for:
    - Documentation debris (process artifacts that should be removed)
    - Stale or missing shadow documentation (auto-fixed by default)

    Exit codes: 0 = passed, 1 = errors found
    """
    config = Config(root_path=path.resolve())

    try:
        result = run_audit(config, fix_shadow=fix)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

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


if __name__ == "__main__":
    main()
