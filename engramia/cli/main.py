# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Engramia CLI.

Commands::

    engramia init               — Create engramia_data/ directory
    engramia serve              — Start the REST API server
    engramia status             — Show metrics and pattern count
    engramia recall "task"      — Semantic search for a task
    engramia aging              — Run pattern aging (decay + prune)

    engramia keys bootstrap     — Create the first owner key (DB auth only)
    engramia keys create        — Create a new API key (DB auth, admin+)
    engramia keys list          — List API keys for current project (DB auth, admin+)
    engramia keys revoke <id>   — Revoke an API key (DB auth, admin+)

    engramia governance retention    — Apply retention policy (delete old patterns)
    engramia governance export       — Export patterns as NDJSON (GDPR Art. 20)
    engramia governance purge-project — Wipe all data for a project (GDPR Art. 17)

Provider selection (for recall):
    Set OPENAI_API_KEY to use OpenAI embeddings (default).
    Set ENGRAMIA_LOCAL_EMBEDDINGS=1 to use local sentence-transformers (no API key).

DB auth commands require ENGRAMIA_DATABASE_URL to be set.
"""

import logging
import os

import typer
from rich.console import Console
from rich.table import Table

_log = logging.getLogger(__name__)

app = typer.Typer(
    name="engramia",
    help="Reusable execution memory and evaluation infrastructure for AI agent frameworks.",
    add_completion=False,
)
keys_app = typer.Typer(name="keys", help="Manage API keys (requires DB auth mode).")
app.add_typer(keys_app)

governance_app = typer.Typer(name="governance", help="Data governance: retention, export, deletion (Phase 5.6).")
app.add_typer(governance_app)

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
            console.print("[red]LocalEmbeddings requires sentence-transformers:[/red] pip install engramia[local]")
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


def _make_db_engine():
    """Create a SQLAlchemy engine from ENGRAMIA_DATABASE_URL."""
    db_url = os.environ.get("ENGRAMIA_DATABASE_URL", "").strip()
    if not db_url:
        console.print(
            "[red]ENGRAMIA_DATABASE_URL is not set.[/red]\n"
            "DB auth commands require a PostgreSQL connection URL."
        )
        raise typer.Exit(1)

    try:
        from sqlalchemy import create_engine

        return create_engine(db_url, pool_pre_ping=True)
    except ImportError:
        console.print("[red]SQLAlchemy not installed.[/red] Install with: pip install engramia[postgres]")
        raise typer.Exit(1) from None


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Directory to initialize."),
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
    console.print("  [cyan]engramia serve --path {path}[/cyan]  — start the REST API")
    console.print("  [cyan]engramia status --path {path}[/cyan] — view metrics")


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to listen on."),
    port: int = typer.Option(8000, help="Port to listen on."),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev mode)."),
    storage: str = typer.Option("json", "--storage", help="Storage backend: 'json' or 'postgres'."),
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Engramia data path (json only)."),
) -> None:
    """Start the Engramia REST API server."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed.[/red] Install with: pip install engramia[api]")
        raise typer.Exit(1) from None

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
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Engramia data directory."),
) -> None:
    """Show Engramia metrics and pattern count."""
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
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Engramia data directory."),
) -> None:
    """Search for patterns matching a task description."""
    from engramia.memory import Memory

    embeddings = _make_embeddings()
    storage = _make_storage(path)
    mem = Memory(embeddings=embeddings, storage=storage)

    console.print(f"Searching for: [italic]{task}[/italic]\n")
    matches = mem.recall(task=task, limit=limit, deduplicate=True)

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
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Engramia data directory."),
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
# keys bootstrap
# ---------------------------------------------------------------------------


@keys_app.command("bootstrap")
def keys_bootstrap(
    tenant_name: str = typer.Option("Default", help="Name of the default tenant."),
    project_name: str = typer.Option("default", help="Name of the default project."),
    key_name: str = typer.Option("Owner key", help="Display name for the first owner key."),
) -> None:
    """Create the first owner API key (only works on an empty api_keys table).

    Requires ENGRAMIA_DATABASE_URL to be set.
    Run ``alembic upgrade head`` before using this command.
    """
    import hashlib
    import secrets
    import uuid

    from sqlalchemy import text

    engine = _make_db_engine()

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM api_keys")).fetchone()
    if count and int(count[0]) > 0:
        console.print(
            "[yellow]Bootstrap already completed.[/yellow]\n"
            "Use an existing admin/owner key to create more keys via the API."
        )
        raise typer.Exit(0)

    # Ensure tenant + project exist
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id, name) VALUES ('default', :name) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"
            ),
            {"name": tenant_name},
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, tenant_id, name) VALUES ('default', 'default', :pname) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"pname": project_name},
        )

    # Generate key
    suffix = secrets.token_urlsafe(32)
    full_key = f"engramia_sk_{suffix}"
    display_prefix = f"engramia_sk_{suffix[:8]}..."
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO api_keys "
                "(id, tenant_id, project_id, name, key_prefix, key_hash, role, created_at) "
                "VALUES (:id, 'default', 'default', :name, :prefix, :hash, 'owner', now()::text)"
            ),
            {"id": key_id, "name": key_name, "prefix": display_prefix, "hash": key_hash},
        )

    console.print("\n[green]✓[/green] Bootstrap complete!\n")
    console.print(f"  Tenant:  [bold]default[/bold] ({tenant_name})")
    console.print(f"  Project: [bold]default[/bold] ({project_name})")
    console.print(f"  Key:     [bold]{key_name}[/bold] (owner role)")
    console.print("\n  [yellow]API Key (save this — shown once only):[/yellow]")
    console.print(f"\n  [bold cyan]{full_key}[/bold cyan]\n")
    console.print("  Add to your environment:")
    console.print(f'  export ENGRAMIA_API_KEY="{full_key}"')


# ---------------------------------------------------------------------------
# keys create
# ---------------------------------------------------------------------------


@keys_app.command("create")
def keys_create(
    name: str = typer.Option(..., "--name", "-n", help="Display name for the key."),
    role: str = typer.Option("editor", "--role", "-r", help="Role: owner, admin, editor, reader."),
    api_key: str = typer.Option(..., "--api-key", envvar="ENGRAMIA_API_KEY", help="Your current API key."),
    base_url: str = typer.Option("http://localhost:8000", "--url", help="Engramia API base URL."),
    max_patterns: int = typer.Option(None, "--max-patterns", help="Pattern quota (default: inherit from project)."),
) -> None:
    """Create a new API key via the REST API."""
    try:
        import httpx
    except ImportError:
        console.print("[red]httpx not installed.[/red] Install with: pip install httpx")
        raise typer.Exit(1) from None

    payload: dict = {"name": name, "role": role}
    if max_patterns is not None:
        payload["max_patterns"] = max_patterns

    resp = httpx.post(
        f"{base_url}/v1/keys",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code != 201:
        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
        raise typer.Exit(1)

    data = resp.json()
    console.print(f"\n[green]✓[/green] Key created: [bold]{data['name']}[/bold] (role={data['role']})")
    console.print("\n  [yellow]API Key (save this — shown once only):[/yellow]")
    console.print(f"\n  [bold cyan]{data['key']}[/bold cyan]\n")


# ---------------------------------------------------------------------------
# keys list
# ---------------------------------------------------------------------------


@keys_app.command("list")
def keys_list(
    api_key: str = typer.Option(..., "--api-key", envvar="ENGRAMIA_API_KEY", help="Your current API key."),
    base_url: str = typer.Option("http://localhost:8000", "--url", help="Engramia API base URL."),
) -> None:
    """List API keys for the current project."""
    try:
        import httpx
    except ImportError:
        console.print("[red]httpx not installed.[/red] Install with: pip install httpx")
        raise typer.Exit(1) from None

    resp = httpx.get(
        f"{base_url}/v1/keys",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code != 200:
        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
        raise typer.Exit(1)

    keys = resp.json().get("keys", [])
    if not keys:
        console.print("[yellow]No keys found.[/yellow]")
        return

    table = Table(show_header=True, show_lines=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Name")
    table.add_column("Prefix", style="cyan")
    table.add_column("Role", style="bold")
    table.add_column("Quota")
    table.add_column("Created")
    table.add_column("Status")

    for k in keys:
        status_str = "[red]Revoked[/red]" if k.get("revoked_at") else "[green]Active[/green]"
        quota = str(k["max_patterns"]) if k.get("max_patterns") else "—"
        created = (k.get("created_at") or "")[:10]
        table.add_row(
            k["id"][:8] + "...",
            k["name"],
            k["key_prefix"],
            k["role"],
            quota,
            created,
            status_str,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# keys revoke
# ---------------------------------------------------------------------------


@keys_app.command("revoke")
def keys_revoke(
    key_id: str = typer.Argument(..., help="ID of the key to revoke."),
    api_key: str = typer.Option(..., "--api-key", envvar="ENGRAMIA_API_KEY", help="Your current API key."),
    base_url: str = typer.Option("http://localhost:8000", "--url", help="Engramia API base URL."),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Revoke an API key immediately."""
    if not confirm:
        typer.confirm(f"Revoke key {key_id[:8]}...? This cannot be undone.", abort=True)

    try:
        import httpx
    except ImportError:
        console.print("[red]httpx not installed.[/red] Install with: pip install httpx")
        raise typer.Exit(1) from None

    resp = httpx.delete(
        f"{base_url}/v1/keys/{key_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code != 200:
        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Key {key_id[:8]}... revoked.")


# ---------------------------------------------------------------------------
# governance retention
# ---------------------------------------------------------------------------


@governance_app.command("retention")
def governance_retention(
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Engramia data directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be deleted without deleting."),
    retention_days: int = typer.Option(365, "--days", help="Retention threshold in days."),
) -> None:
    """Apply retention policy — delete patterns older than the configured threshold.

    Works with JSON storage. For PostgreSQL, prefer POST /v1/governance/retention/apply.
    """
    from engramia.governance.retention import RetentionManager

    storage = _make_storage(path)
    manager = RetentionManager(default_retention_days=retention_days)
    result = manager.apply(storage, dry_run=dry_run)

    if dry_run:
        console.print(
            f"[yellow]Dry run:[/yellow] Would delete [bold]{result.purged_count}[/bold] pattern(s) "
            f"older than {retention_days} days."
        )
    elif result.purged_count == 0:
        console.print(f"[green]✓[/green] Retention applied — no patterns older than {retention_days} days.")
    else:
        console.print(
            f"[green]✓[/green] Retention applied — deleted [bold]{result.purged_count}[/bold] pattern(s)."
        )


# ---------------------------------------------------------------------------
# governance export
# ---------------------------------------------------------------------------


@governance_app.command("export")
def governance_export(
    output: str = typer.Option("-", "--output", "-o", help="Output file path. Use '-' for stdout."),
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Engramia data directory."),
    classification: str = typer.Option(
        None, "--classification", "-c", help="Comma-separated classification filter."
    ),
) -> None:
    """Export all patterns to NDJSON (GDPR Art. 20 data portability).

    Each line is a JSON object. Use --classification to filter by sensitivity level.

    Example::

        engramia governance export --output patterns.ndjson
        engramia governance export --classification public,internal | gzip > archive.ndjson.gz
    """
    import json
    import sys

    from engramia.governance.export import DataExporter

    storage = _make_storage(path)
    cls_filter = [c.strip() for c in classification.split(",")] if classification else None
    exporter = DataExporter()

    out = open(output, "w", encoding="utf-8") if output != "-" else sys.stdout
    count = 0
    try:
        for record in exporter.stream(storage, classification_filter=cls_filter):
            out.write(json.dumps(record, default=str) + "\n")
            count += 1
    finally:
        if output != "-":
            out.close()

    if output != "-":
        console.print(f"[green]✓[/green] Exported [bold]{count}[/bold] patterns to [cyan]{output}[/cyan].")


# ---------------------------------------------------------------------------
# governance purge-project (GDPR Art. 17)
# ---------------------------------------------------------------------------


@governance_app.command("purge-project")
def governance_purge_project(
    project_id: str = typer.Argument(..., help="Project ID to permanently wipe."),
    tenant_id: str = typer.Option("default", "--tenant", "-t", help="Tenant ID."),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Engramia data directory."),
) -> None:
    """Permanently delete all data for a project (GDPR Art. 17).

    This is irreversible. Patterns and embeddings are deleted immediately.
    Requires ENGRAMIA_DATABASE_URL for full cascade (jobs, keys, audit log).
    """
    if not confirm:
        typer.confirm(
            f"Permanently delete ALL data for project '{project_id}' in tenant '{tenant_id}'? "
            "This cannot be undone.",
            abort=True,
        )

    from engramia._context import reset_scope, set_scope
    from engramia.governance.deletion import ScopedDeletion
    from engramia.types import Scope

    storage = _make_storage(path)
    engine = None
    db_url = os.environ.get("ENGRAMIA_DATABASE_URL", "").strip()
    if db_url:
        try:
            from sqlalchemy import create_engine
            engine = create_engine(db_url, pool_pre_ping=True)
        except ImportError:
            pass

    deletion = ScopedDeletion(engine=engine)
    token = set_scope(Scope(tenant_id=tenant_id, project_id=project_id))
    try:
        result = deletion.delete_project(storage, tenant_id=tenant_id, project_id=project_id)
    finally:
        reset_scope(token)

    console.print(f"\n[green]✓[/green] Project [bold]{project_id}[/bold] wiped.")
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="dim")
    table.add_column("Value", style="bold")
    table.add_row("Patterns deleted", str(result.patterns_deleted))
    table.add_row("Jobs deleted", str(result.jobs_deleted))
    table.add_row("Keys revoked", str(result.keys_revoked))
    console.print(table)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for ``engramia`` CLI command."""
    logging.basicConfig(level=logging.WARNING)
    app()


if __name__ == "__main__":
    main()
