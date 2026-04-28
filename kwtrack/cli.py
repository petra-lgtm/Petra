from __future__ import annotations

import sys
from pathlib import Path

import click

from kwtrack import __version__
from kwtrack.db import connect, init_schema, resolve_db_path
from kwtrack.importers.cerebro import import_cerebro_csv
from kwtrack.markets import MARKETS


def _db_option(f):
    return click.option(
        "--db",
        "db_path",
        default=None,
        envvar="KWTRACK_DB",
        help="Path to SQLite database (default ./kwtrack.db, or $KWTRACK_DB).",
    )(f)


@click.group()
@click.version_option(__version__, prog_name="kwtrack")
def main() -> None:
    """Amazon keyword tracking across US/UK/DE/FR markets."""


@main.command()
@_db_option
def init(db_path: str | None) -> None:
    """Create or upgrade the SQLite database."""
    path = resolve_db_path(db_path)
    conn = connect(path)
    try:
        init_schema(conn)
    finally:
        conn.close()
    click.echo(f"Initialized database at {path}")


@main.group("import")
def import_group() -> None:
    """Import data from external sources."""


@import_group.command("cerebro")
@click.option(
    "--market",
    type=click.Choice(MARKETS, case_sensitive=False),
    required=True,
    help="Market the file was exported for.",
)
@click.option(
    "--file",
    "csv_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the Helium10 Cerebro CSV.",
)
@click.option("--note", default=None, help="Optional note stored on the import run.")
@_db_option
def import_cerebro_cmd(
    market: str,
    csv_file: Path,
    note: str | None,
    db_path: str | None,
) -> None:
    """Import a Helium10 Cerebro CSV export."""
    conn = connect(db_path)
    try:
        init_schema(conn)
        try:
            result = import_cerebro_csv(conn, csv_file, market, note=note)
        except RuntimeError as e:
            raise click.ClickException(str(e))
    finally:
        conn.close()
    click.echo(
        f"Cerebro import #{result.import_run_id} ({market.upper()}): "
        f"{result.rows_inserted} snapshots, {result.new_keywords} new keywords."
    )


@import_group.command("adlabs")
def import_adlabs_cmd() -> None:
    """Import an AdLabs ad search-term export. (Not yet implemented.)"""
    raise click.ClickException("AdLabs importer not yet implemented.")


if __name__ == "__main__":
    main()
