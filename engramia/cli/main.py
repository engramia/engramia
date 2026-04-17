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

    engramia auth generate-keys      — Generate RSA key pair for RS256 JWT signing

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

auth_app = typer.Typer(name="auth", help="Cloud auth utilities (JWT key management).")
app.add_typer(auth_app)

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
            "[red]ENGRAMIA_DATABASE_URL is not set.[/red]\nDB auth commands require a PostgreSQL connection URL."
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
    host: str = typer.Option("0.0.0.0", help="Host to listen on."),  # nosec B104
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
        proxy_headers=True,
        forwarded_allow_ips="*",
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
# reindex
# ---------------------------------------------------------------------------


@app.command()
def reindex(
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Engramia data directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be re-embedded without writing."),
) -> None:
    """Re-embed all stored patterns with the current embedding provider.

    Use this command after changing the embedding model or provider to ensure
    all stored pattern embeddings are consistent with the current configuration.
    """
    from engramia.memory import _EMBED_META_KEY

    embeddings = _make_embeddings()
    storage = _make_storage(path)

    # List all pattern keys
    pattern_keys = storage.list_keys(prefix="patterns/")
    if not pattern_keys:
        console.print("[yellow]No patterns found — nothing to reindex.[/yellow]")
        return

    provider_name = type(embeddings).__name__
    model_name = getattr(embeddings, "_model", None) or getattr(embeddings, "_model_name", "unknown")

    console.print(
        f"Reindexing [bold]{len(pattern_keys)}[/bold] pattern(s) "
        f"using [cyan]{provider_name}[/cyan] model=[cyan]{model_name}[/cyan]"
    )
    if dry_run:
        console.print("[yellow]Dry-run mode — no changes will be written.[/yellow]")

    ok = 0
    failed = 0
    for key in pattern_keys:
        data = storage.load(key)
        if not data or "task" not in data:
            continue
        try:
            embedding = embeddings.embed(data["task"])
            if not dry_run:
                storage.save_embedding(key, embedding)
            ok += 1
        except Exception as exc:
            console.print(f"[red]Failed[/red] {key}: {exc}")
            failed += 1

    if not dry_run:
        storage.save(
            _EMBED_META_KEY,
            {
                "provider": provider_name,
                "model": str(model_name),
                "created_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
                "reindexed_count": ok,
            },
        )

    status_str = "[green]✓[/green]" if not failed else "[yellow]⚠[/yellow]"
    console.print(f"{status_str} Reindex complete — {ok} re-embedded, {failed} failed.")


# ---------------------------------------------------------------------------
# migrate json-to-postgres
# ---------------------------------------------------------------------------


@app.command("migrate")
def migrate(
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Source JSON storage directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview migration without writing to PostgreSQL."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing patterns in PostgreSQL."),
) -> None:
    """Migrate patterns from JSON storage to PostgreSQL.

    Reads all patterns (and their embeddings) from the local JSON storage
    directory and writes them into the PostgreSQL database configured by
    ENGRAMIA_DATABASE_URL. Existing patterns are skipped unless --overwrite
    is set.

    \b
    Requires:
      - ENGRAMIA_DATABASE_URL to be set
      - Alembic migrations applied (alembic upgrade head)
      - pip install engramia[postgres]
    """
    from engramia._util import PATTERNS_PREFIX
    from engramia.providers.json_storage import JSONStorage

    db_url = os.environ.get("ENGRAMIA_DATABASE_URL", "").strip()
    if not db_url:
        console.print("[red]ENGRAMIA_DATABASE_URL is not set.[/red]")
        raise typer.Exit(1)

    try:
        from engramia.providers.postgres import PostgresStorage
    except ImportError:
        console.print("[red]PostgreSQL support not installed.[/red] Install with: pip install engramia[postgres]")
        raise typer.Exit(1) from None

    src = JSONStorage(path=path)
    pattern_keys = src.list_keys(prefix=PATTERNS_PREFIX)

    if not pattern_keys:
        console.print("[yellow]No patterns found in JSON storage — nothing to migrate.[/yellow]")
        return

    console.print(f"Found [bold]{len(pattern_keys)}[/bold] pattern(s) in JSON storage at [cyan]{path}[/cyan]")

    if dry_run:
        console.print("[yellow]Dry-run mode — no data will be written to PostgreSQL.[/yellow]")
        for key in pattern_keys:
            data = src.load(key)
            task = data.get("task", "?") if data else "?"
            console.print(f"  [dim]{key}[/dim] — {task[:60]}")
        return

    dst = PostgresStorage()
    migrated = 0
    skipped = 0
    failed = 0

    for key in pattern_keys:
        data = src.load(key)
        if data is None:
            continue

        existing = dst.load(key)
        if existing is not None and not overwrite:
            skipped += 1
            continue

        try:
            dst.save(key, data)

            # Migrate embedding if available
            src_embeddings = src._load_embeddings_for_root(src._effective_root())
            if key in src_embeddings:
                dst.save_embedding(key, src_embeddings[key])

            migrated += 1
        except Exception as exc:
            console.print(f"[red]Failed[/red] {key}: {exc}")
            failed += 1

    console.print(f"[green]✓[/green] Migration complete — {migrated} migrated, {skipped} skipped, {failed} failed.")


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
        console.print(f"[green]✓[/green] Retention applied — deleted [bold]{result.purged_count}[/bold] pattern(s).")


# ---------------------------------------------------------------------------
# governance export
# ---------------------------------------------------------------------------


@governance_app.command("export")
def governance_export(
    output: str = typer.Option("-", "--output", "-o", help="Output file path. Use '-' for stdout."),
    path: str = typer.Option("./engramia_data", "--path", "-p", help="Engramia data directory."),
    classification: str = typer.Option(None, "--classification", "-c", help="Comma-separated classification filter."),
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

    import contextlib
    from typing import TextIO

    count = 0
    out: TextIO
    with contextlib.ExitStack() as stack:
        if output != "-":
            out = stack.enter_context(open(output, "w", encoding="utf-8"))
        else:
            out = sys.stdout
        for record in exporter.stream(storage, classification_filter=cls_filter):
            out.write(json.dumps(record, default=str) + "\n")
            count += 1

    if output != "-":
        console.print(f"[green]✓[/green] Exported [bold]{count}[/bold] patterns to [cyan]{output}[/cyan].")

    # Audit the export into the DB audit_log when PostgreSQL is configured.
    # Fire-and-forget: failures are logged but never interrupt the export.
    db_url = os.environ.get("ENGRAMIA_DATABASE_URL", "").strip()
    if db_url:
        try:
            from sqlalchemy import create_engine

            from engramia.api.audit import log_db_event

            _engine = create_engine(db_url, pool_pre_ping=True)
            log_db_event(
                _engine,
                tenant_id="default",
                project_id="default",
                action="data_exported",
                resource_type="patterns",
                resource_id=f"count:{count}",
            )
        except Exception as exc:
            _log.debug("CLI export: DB audit failed (non-fatal): %s", exc)


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
            f"Permanently delete ALL data for project '{project_id}' in tenant '{tenant_id}'? This cannot be undone.",
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
# Auth utilities
# ---------------------------------------------------------------------------


@auth_app.command("generate-keys")
def auth_generate_keys(
    out_dir: str = typer.Option(".", "--out-dir", "-o", help="Directory to write key files into."),
    key_size: int = typer.Option(2048, "--key-size", help="RSA key size in bits (2048 or 4096)."),
) -> None:
    """Generate an RSA key pair for RS256 JWT signing.

    Writes private_key.pem and public_key.pem to --out-dir.

    Set these env vars to activate RS256:
      ENGRAMIA_JWT_PRIVATE_KEY=/path/to/private_key.pem
      ENGRAMIA_JWT_PUBLIC_KEY=/path/to/public_key.pem
    """
    import pathlib

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if key_size not in (2048, 4096):
        console.print(f"[red]--key-size must be 2048 or 4096 (got {key_size})[/red]")
        raise typer.Exit(1)

    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    private_path = out / "private_key.pem"
    public_path = out / "public_key.pem"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_pem)
    private_path.chmod(0o600)
    public_path.write_bytes(public_pem)

    console.print(f"[green]RSA {key_size}-bit key pair generated:[/green]")
    console.print(f"  Private key: {private_path.resolve()}")
    console.print(f"  Public key:  {public_path.resolve()}")
    console.print()
    console.print("[yellow]Add to your environment:[/yellow]")
    console.print(f"  ENGRAMIA_JWT_PRIVATE_KEY={private_path.resolve()}")
    console.print(f"  ENGRAMIA_JWT_PUBLIC_KEY={public_path.resolve()}")
    console.print()
    console.print("[red]Keep private_key.pem secret — do not commit it to version control.[/red]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for ``engramia`` CLI command."""
    logging.basicConfig(level=logging.WARNING)
    app()


if __name__ == "__main__":
    main()
