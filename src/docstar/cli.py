"""Click CLI for Docstar."""

from pathlib import Path

import click

from .config import Config
from .shadow import generate_shadow_docs, check_shadow_docs


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


if __name__ == "__main__":
    main()
