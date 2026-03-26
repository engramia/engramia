# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Engramia CLI.

Commands::

    agent-brain init          — Create brain_data/ directory
    agent-brain serve         — Start the REST API server
    agent-brain status        — Show metrics and pattern count
    agent-brain recall "task" — Semantic search for a task
    agent-brain aging         — Run pattern aging (decay + prune)

Provider selection (for recall):
    Set OPENAI_API_KEY to use OpenAI embeddings (default).
    Set ENGRAMIA_LOCAL_EMBEDDINGS=1 to use local sentence-transformers (no API key).
"""

import logging
import os

import typer
from rich.console import Console
from rich.table import Table

_log = logging.getLogger(__name__)

app = typer.Typer(
    name="agent-brain",
    help="Self-learning memory layer for AI agent frameworks.",
    add_completion=False,
)
console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storage(path: str):
    """Create a JSONStorage instance at the given path."""
    from engramia.providers.json_storage import JSONStorage

    return JSONStorage(path=path)


def _make_embeddings():
    """Return an embedding provider based on environment variables."""
    if os.environ.get("ENGRAMIA_LOCAL_EMBEDDINGS"):
        try:
            from engramia.providers.local_embeddings import LocalEmbeddings

            return LocalEmbeddings()
        except ImportError:
            console.print("[red]LocalEmbeddings requires sentence-transformers:[/red] pip install agent-brain[local]")
            raise typer.Exit(1) from None

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        console.print(
            "[red]No embedding provider configured.[/red]\n"
            "Set [bold]OPENAI_API_KEY[/bold] to use OpenAI embeddings, or\n"
            "set [bold]ENGRAMIA_LOCAL_EMBEDDINGS=1[/bold] to use local sentence-transformers."
        )
        raise typer.Exit(1)

    from engramia.providers.openai import OpenAIEmbeddings

    return OpenAIEmbeddings()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    path: str = typer.Option("./brain_data", "--path", "-p", help="Directory to initialize."),
) -> None:
    """Initialize a new engramia data directory."""
    import pathlib

    p = pathlib.Path(path)
    if p.exists():
        console.print(f"[yellow]Directory already exists:[/yellow] {p.resolve()}")
        raise typer.Exit(0)

    p.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✓[/green] Initialized engramia data directory: [bold]{p.resolve()}[/bold]")
    console.print("\nNext steps:")
    console.print("  [cyan]agent-brain serve --path {path}[/cyan]  — start the REST API")
    console.print("  [cyan]agent-brain status --path {path}[/cyan] — view metrics")


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to listen on."),
    port: int = typer.Option(8000, help="Port to listen on."),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev mode)."),
    storage: str = typer.Option("json", "--storage", help="Storage backend: 'json' or 'postgres'."),
    path: str = typer.Option("./brain_data", "--path", "-p", help="Brain data path (json only)."),
) -> None:
    """Start the Brain REST API server."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed.[/red] Install with: pip install agent-brain[api]")
        raise typer.Exit(1) from None

    # Set storage env var so create_app() picks it up
    if storage == "json":
        os.environ.setdefault("ENGRAMIA_STORAGE", "json")
        os.environ.setdefault("ENGRAMIA_DATA_PATH", path)
    else:
        os.environ.setdefault("ENGRAMIA_STORAGE", storage)

    console.print(f"[green]Starting Engramia API[/green] on [bold]http://{host}:{port}[/bold]  (storage={storage})")
    console.print(f"  Swagger UI: [cyan]http://{host}:{port}/docs[/cyan]")

    uvicorn.run(
        "engramia.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    path: str = typer.Option("./brain_data", "--path", "-p", help="engramia data directory."),
) -> None:
    """Show Brain metrics and pattern count."""
    from engramia.core.metrics import MetricsStore
    from engramia.core.success_patterns import SuccessPatternStore

    storage = _make_storage(path)
    metrics_store = MetricsStore(storage)
    pattern_store = SuccessPatternStore(storage)

    m = metrics_store.get()
    pattern_count = pattern_store.get_count()

    table = Table(title=f"Engramia Status — {path}", show_header=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="bold")

    table.add_row("Patterns stored", str(pattern_count))
    table.add_row("Total runs", str(m.runs))
    table.add_row(
        "Success rate",
        f"{m.success_rate:.1%}" if m.runs > 0 else "—",
    )
    table.add_row(
        "Avg eval score",
        f"{m.avg_eval_score:.2f}" if m.avg_eval_score is not None else "—",
    )
    table.add_row(
        "Pipeline reuse",
        f"{m.pipeline_reuse / m.runs:.1%}" if m.runs > 0 else "—",
    )

    console.print(table)


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


@app.command()
def recall(
    task: str = typer.Argument(..., help="Task description to search for."),
    limit: int = typer.Option(5, "--limit", "-n", help="Maximum number of matches."),
    path: str = typer.Option("./brain_data", "--path", "-p", help="engramia data directory."),
) -> None:
    """Search for patterns matching a task description."""
    from engramia.brain import Memory

    embeddings = _make_embeddings()
    storage = _make_storage(path)
    brain = Memory(embeddings=embeddings, storage=storage)

    console.print(f"Searching for: [italic]{task}[/italic]\n")
    matches = brain.recall(task=task, limit=limit, deduplicate=True)

    if not matches:
        console.print("[yellow]No matching patterns found.[/yellow]")
        return

    table = Table(show_header=True, show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Task", min_width=30)
    table.add_column("Score", style="cyan", width=7)
    table.add_column("Similarity", width=10)
    table.add_column("Tier", width=10)

    for i, m in enumerate(matches, 1):
        table.add_row(
            str(i),
            m.pattern.task[:80] + ("…" if len(m.pattern.task) > 80 else ""),
            f"{m.pattern.success_score:.2f}",
            f"{m.similarity:.3f}",
            m.reuse_tier,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# aging
# ---------------------------------------------------------------------------


@app.command()
def aging(
    path: str = typer.Option("./brain_data", "--path", "-p", help="engramia data directory."),
) -> None:
    """Run pattern aging — apply time-based decay and prune stale patterns."""
    from engramia.core.success_patterns import SuccessPatternStore

    storage = _make_storage(path)
    store = SuccessPatternStore(storage)
    pruned = store.run_aging()

    if pruned == 0:
        console.print("[green]✓[/green] Aging complete — no patterns pruned.")
    else:
        console.print(f"[yellow]Aging complete — pruned {pruned} pattern(s).[/yellow]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for ``agent-brain`` CLI command."""
    logging.basicConfig(level=logging.WARNING)
    app()


if __name__ == "__main__":
    main()
