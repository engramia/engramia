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

cleanup_app = typer.Typer(name="cleanup", help="Scheduled maintenance tasks (intended for cron).")
app.add_typer(cleanup_app)

cloud_app = typer.Typer(name="cloud", help="Cloud admin: manual tenant onboarding.")
app.add_typer(cloud_app)

credentials_app = typer.Typer(
    name="credentials",
    help="BYOK credential subsystem operations (Phase 6.6).",
)
app.add_typer(credentials_app)

waitlist_app = typer.Typer(
    name="waitlist",
    help="Cloud onboarding waitlist (Variant A — manual admin approval).",
)
app.add_typer(waitlist_app)

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
    recency_weight: float = typer.Option(
        0.0,
        "--recency-weight",
        min=0.0,
        max=1.0,
        help="Bias toward recently-stored patterns (0.0 = off, 1.0 = full exponential decay).",
    ),
    recency_half_life_days: float = typer.Option(
        30.0,
        "--recency-half-life",
        min=0.0,
        help="Half-life of the recency decay, in days. Ignored when --recency-weight=0.",
    ),
) -> None:
    """Search for patterns matching a task description."""
    from engramia.memory import Memory

    embeddings = _make_embeddings()
    storage = _make_storage(path)
    mem = Memory(embeddings=embeddings, storage=storage)

    console.print(f"Searching for: [italic]{task}[/italic]\n")
    matches = mem.recall(
        task=task,
        limit=limit,
        deduplicate=True,
        recency_weight=recency_weight,
        recency_half_life_days=recency_half_life_days,
    )

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
# Cleanup commands (scheduled maintenance)
# ---------------------------------------------------------------------------


@cleanup_app.command("unverified-users")
def cleanup_unverified_users(
    reminder_after_days: int = typer.Option(
        7, "--reminder-after-days", help="Send a reminder to users unverified this long."
    ),
    delete_after_days: int = typer.Option(
        14, "--delete-after-days", help="Delete pending accounts unverified this long."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without making changes."),
) -> None:
    """Notify and/or delete cloud users who never confirmed their email.

    Two stages, run in this order:
      1. Users signed up more than ``--reminder-after-days`` ago, not yet verified,
         with no prior reminder → send reminder email + stamp ``reminder_sent_at``.
      2. Users signed up more than ``--delete-after-days`` ago and still not verified
         → cascade delete (user → tenant → project → api_keys via FK ON DELETE CASCADE).

    Intended to run from cron once a day. Safe to run more frequently — both stages
    are idempotent (the reminder column guards duplicate emails; delete is monotonic).
    """
    from sqlalchemy import create_engine, text

    from engramia.api.cloud_auth import _create_verification_token, _dashboard_url
    from engramia.email import EmailNotConfigured, send_email
    from engramia.email.templates import reminder_email

    db_url = os.environ.get("ENGRAMIA_DATABASE_URL", "").strip()
    if not db_url:
        console.print("[red]ENGRAMIA_DATABASE_URL not set[/red]")
        raise typer.Exit(1)

    if delete_after_days <= reminder_after_days:
        console.print("[red]--delete-after-days must be greater than --reminder-after-days[/red]")
        raise typer.Exit(1)

    engine = create_engine(db_url, pool_pre_ping=True)

    # -------- Stage 1: reminders --------
    with engine.connect() as conn:
        reminder_rows = conn.execute(
            text(
                "SELECT id, email, name, created_at FROM cloud_users "
                "WHERE email_verified = false "
                "  AND provider = 'credentials' "
                "  AND created_at < now() - (:rd || ' days')::interval "
                "  AND created_at > now() - (:dd || ' days')::interval "
                "  AND reminder_sent_at IS NULL"
            ),
            {"rd": reminder_after_days, "dd": delete_after_days},
        ).fetchall()

    sent_count = 0
    for row in reminder_rows:
        user_id, email, name = str(row[0]), str(row[1]), row[2]
        if dry_run:
            console.print(f"[yellow]DRY-RUN reminder → {email}[/yellow]")
            sent_count += 1
            continue

        token = _create_verification_token(engine, user_id)
        verify_url = f"{_dashboard_url()}/verify?token={token}"
        subject, text_body, html = reminder_email(
            verify_url=verify_url,
            recipient_name=name,
            days_since_signup=reminder_after_days,
            days_until_delete=delete_after_days - reminder_after_days,
        )
        try:
            send_email(to=email, subject=subject, html=html, text=text_body)
        except EmailNotConfigured:
            console.print("[red]SMTP not configured — aborting reminder stage[/red]")
            raise typer.Exit(1) from None
        except Exception as exc:  # smtplib.SMTPException or network
            console.print(f"[yellow]Reminder send failed for {email}: {exc}[/yellow]")
            continue

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE cloud_users SET reminder_sent_at = now() WHERE id = :uid"),
                {"uid": user_id},
            )
        sent_count += 1

    # -------- Stage 2: deletes --------
    with engine.connect() as conn:
        delete_rows = conn.execute(
            text(
                "SELECT id, email, tenant_id FROM cloud_users "
                "WHERE email_verified = false "
                "  AND provider = 'credentials' "
                "  AND created_at < now() - (:dd || ' days')::interval"
            ),
            {"dd": delete_after_days},
        ).fetchall()

    deleted_count = 0
    for row in delete_rows:
        user_id, email, tenant_id = str(row[0]), str(row[1]), str(row[2])
        if dry_run:
            console.print(f"[red]DRY-RUN delete → {email} (tenant {tenant_id})[/red]")
            deleted_count += 1
            continue

        # Delete the user; FK cascade wipes email_verification_tokens.
        # Tenant + project + api_keys are purged explicitly since cloud_users
        # references tenants (not the other way around) so cascading stops at
        # the user row.
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM cloud_users WHERE id = :uid"), {"uid": user_id})
            conn.execute(text("DELETE FROM api_keys WHERE tenant_id = :tid"), {"tid": tenant_id})
            conn.execute(text("DELETE FROM projects WHERE tenant_id = :tid"), {"tid": tenant_id})
            conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        console.print(f"[red]Deleted pending account:[/red] {email} (tenant {tenant_id})")
        deleted_count += 1

    console.print()
    console.print(
        f"[green]Cleanup complete[/green] — reminders sent: {sent_count}, accounts deleted: {deleted_count}"
        f"{' (dry-run)' if dry_run else ''}"
    )


@cleanup_app.command("deleted-accounts")
def cleanup_deleted_accounts(
    grace_period_days: int = typer.Option(
        30,
        "--grace-period-days",
        help="Days to keep soft-deleted users before hard-delete. Mirrors the GDPR-friendly window we promise in the Privacy Policy.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without making changes."),
) -> None:
    """Hard-delete cloud_users + tenants soft-deleted by self-service flow >= grace period.

    Phase 1 of the self-service deletion flow (DELETE /v1/me) anonymises the
    cloud_user row and soft-deletes the tenant immediately, but keeps the rows
    around for a 30-day grace period — long enough that an accidental deletion
    can be reversed by support before the data is irrecoverable, short enough
    to satisfy GDPR Art. 5(1)(e) ("storage limitation").

    This command runs Phase 2: walk every cloud_user with
    ``deleted_at < now() - grace_period_days`` and delete the underlying rows
    plus the orphaned consumed deletion-request tokens. Audit log entries for
    the deletion event itself are preserved (regulatory record).

    Idempotent and safe to run from cron daily.
    """
    from sqlalchemy import create_engine, text

    db_url = os.environ.get("ENGRAMIA_DATABASE_URL", "").strip()
    if not db_url:
        console.print("[red]ENGRAMIA_DATABASE_URL not set[/red]")
        raise typer.Exit(1)

    engine = create_engine(db_url, pool_pre_ping=True)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, tenant_id, deleted_at FROM cloud_users "
                "WHERE deleted_at IS NOT NULL "
                "  AND deleted_at < now() - (:gd || ' days')::interval"
            ),
            {"gd": grace_period_days},
        ).fetchall()

    if not rows:
        console.print(f"[green]Nothing to clean up[/green] (no users soft-deleted >= {grace_period_days}d ago)")
        return

    hard_deleted = 0
    for row in rows:
        user_id, tenant_id, deleted_at = str(row[0]), str(row[1]), row[2]
        if dry_run:
            console.print(
                f"[yellow]DRY-RUN hard-delete[/yellow] user={user_id} tenant={tenant_id} (soft-deleted at {deleted_at})"
            )
            hard_deleted += 1
            continue

        # Order matters: children first (consumed deletion tokens, api_keys
        # rows that ScopedDeletion only revoked but kept), then user, then
        # tenant. Audit log + email_verification_tokens have ON DELETE CASCADE
        # to cloud_users / tenants so they go with the parent.
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM account_deletion_requests WHERE user_id = :uid"),
                {"uid": user_id},
            )
            conn.execute(text("DELETE FROM api_keys WHERE tenant_id = :tid"), {"tid": tenant_id})
            conn.execute(text("DELETE FROM cloud_users WHERE id = :uid"), {"uid": user_id})
            conn.execute(text("DELETE FROM projects WHERE tenant_id = :tid"), {"tid": tenant_id})
            conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})

        console.print(f"[red]Hard-deleted[/red] user={user_id} tenant={tenant_id} (soft-deleted at {deleted_at})")
        hard_deleted += 1

    console.print()
    console.print(
        f"[green]Hard-delete complete[/green] — accounts removed: {hard_deleted}{' (dry-run)' if dry_run else ''}"
    )


# ---------------------------------------------------------------------------
# Cloud admin (manual tenant onboarding)
# ---------------------------------------------------------------------------


@cloud_app.command("create-account")
def cloud_create_account(
    email: str = typer.Argument(..., help="User email address (also the login)."),
    name: str | None = typer.Option(None, "--name", help="Display name; defaults to email local-part."),
    password: str | None = typer.Option(
        None,
        "--password",
        help="Login password. If omitted, a random 16-char password is generated and printed.",
    ),
    plan: str = typer.Option(
        "developer",
        "--plan",
        help="Plan tier (developer | pro | team | business | enterprise). Sets tenants.plan_tier.",
    ),
) -> None:
    """Manually onboard a cloud tenant — bypasses email verification and SMTP.

    Creates tenant + project + cloud_user (email_verified=True) + owner API key
    in a single transaction, then prints the credentials. Intended for pilot
    onboarding before self-serve registration is exposed publicly.

    Requires ``ENGRAMIA_DATABASE_URL`` to point at the cloud database.
    """
    import secrets

    from sqlalchemy import text

    from engramia.api.cloud_auth import _create_registration, _hash_password

    # "sandbox" is the legacy free-tier name (pre-Phase-6.6); we still
    # accept it for compatibility with operator scripts that haven't
    # caught up to the rename, but log a deprecation hint.
    valid_plans = {"developer", "pro", "team", "business", "enterprise", "sandbox"}
    if plan not in valid_plans:
        console.print(f"[red]Invalid plan tier:[/red] {plan!r} (expected developer|pro|team|business|enterprise)")
        raise typer.Exit(1)
    if plan == "sandbox":
        console.print("[yellow]Note:[/yellow] 'sandbox' is deprecated — using 'developer' instead.")
        plan = "developer"

    engine = _make_db_engine()

    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT id FROM cloud_users WHERE email = :email AND deleted_at IS NULL"),
            {"email": email},
        ).fetchone()
    if existing is not None:
        console.print(f"[red]Account already exists[/red] for {email} (id={existing[0]})")
        raise typer.Exit(1)

    plain_password = password or secrets.token_urlsafe(12)
    password_hash = _hash_password(plain_password)

    result = _create_registration(
        engine,
        email=email,
        password_hash=password_hash,
        name=name or email.split("@")[0],
        provider="credentials",
        provider_id=None,
        email_verified=True,
    )

    if plan != "developer":
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE tenants SET plan_tier = :plan WHERE id = :tid"),
                {"plan": plan, "tid": result["tenant_id"]},
            )

    # Manually-provisioned accounts use a one-time password — force the user
    # to change it on first login (ADR-007). The Dashboard middleware blocks
    # access to all routes until the user calls POST /auth/change-password.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE cloud_users SET must_change_password = true WHERE id = :uid"),
            {"uid": result["user_id"]},
        )

    console.print()
    console.print("[green]Account created[/green]")
    console.print(f"  email      : {email}")
    if password is None:
        console.print(f"  password   : [bold]{plain_password}[/bold]  (auto-generated — share securely)")
    else:
        console.print("  password   : (as supplied)")
    console.print(f"  plan       : {plan}")
    console.print(f"  tenant_id  : {result['tenant_id']}")
    console.print(f"  project_id : {result['project_id']}")
    console.print(f"  user_id    : {result['user_id']}")
    console.print(f"  api_key    : [bold]{result['api_key']}[/bold]  (owner role — show once, store securely)")
    console.print()
    console.print("[yellow]Note:[/yellow] email_verified=True; the user can log in immediately.")


@cloud_app.command("list-accounts")
def cloud_list_accounts(
    limit: int = typer.Option(50, "--limit", help="Max rows to return."),
    plan: str | None = typer.Option(None, "--plan", help="Filter by plan tier."),
) -> None:
    """List active cloud accounts (skips soft-deleted users)."""
    from sqlalchemy import text

    engine = _make_db_engine()
    sql = (
        "SELECT u.email, u.tenant_id, t.plan_tier, u.created_at, u.last_login_at "
        "FROM cloud_users u JOIN tenants t ON t.id = u.tenant_id "
        "WHERE u.deleted_at IS NULL"
    )
    params: dict = {"lim": limit}
    if plan:
        sql += " AND t.plan_tier = :plan"
        params["plan"] = plan
    sql += " ORDER BY u.created_at DESC LIMIT :lim"

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    if not rows:
        console.print("[dim]No accounts found.[/dim]")
        return

    for email, tenant_id, plan_tier, created_at, last_login in rows:
        last = last_login.isoformat() if last_login else "never"
        console.print(
            f"  {email:<40} tenant={tenant_id:<24} plan={plan_tier:<10} created={created_at} last_login={last}"
        )
    console.print(f"\n[dim]{len(rows)} account(s)[/dim]")


# ---------------------------------------------------------------------------
# Credentials backend migration (Phase 6.6 #6)
# ---------------------------------------------------------------------------


@credentials_app.command("migrate-to-vault")
def credentials_migrate_to_vault(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be migrated without writing back."),
    tenant: str | None = typer.Option(None, "--tenant", help="Limit migration to one tenant id (default: all)."),
    batch_size: int = typer.Option(100, "--batch-size", min=1, max=1000, help="Rows per checkpoint."),
    continue_from: str | None = typer.Option(
        None, "--continue-from", help="Resume from a specific row id (after a crashed run)."
    ),
    reverse: bool = typer.Option(
        False,
        "--reverse",
        help="Migrate vault → local instead (rollback path).",
    ),
) -> None:
    """Bulk migrate ``tenant_credentials`` rows between backends.

    Default direction is ``local → vault``: reads each row whose
    ``backend = 'local'``, decrypts via the local AES-GCM backend
    (operator must still hold ``ENGRAMIA_CREDENTIALS_KEY`` at migration
    time), re-encrypts via the configured Vault backend, and writes the
    new ciphertext back with ``backend = 'vault'``.

    With ``--reverse``: ``vault → local``. Useful for rollback after a
    failed Vault rollout.

    The script is idempotent: rows already at the destination backend
    are skipped (the WHERE clause filters by source backend). A crashed
    run can be resumed with ``--continue-from <last_id>``.

    Required env:
        ENGRAMIA_DATABASE_URL — DB connection.
        ENGRAMIA_CREDENTIALS_KEY — local backend (always; even on reverse,
            we re-encrypt to local).
        ENGRAMIA_VAULT_* — vault backend env vars (always; same reason).
    """
    engine = _make_db_engine()

    # Build BOTH backends — migration needs source AND destination
    # available simultaneously regardless of direction.
    from engramia.credentials.backends.local import LocalAESGCMBackend
    from engramia.credentials.backends.vault import VaultTransitBackend

    try:
        local = LocalAESGCMBackend.from_env()
    except Exception as exc:
        console.print(f"[red]Local backend init failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    try:
        vault = VaultTransitBackend.from_env(dict(os.environ))
    except Exception as exc:
        console.print(f"[red]Vault backend init failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    src_backend, dst_backend = (vault, local) if reverse else (local, vault)
    src_id, dst_id = src_backend.backend_id, dst_backend.backend_id

    from sqlalchemy import text

    from engramia.credentials.backend import EncryptedBlob

    direction_label = f"{src_id} → {dst_id}"
    console.print(f"[bold]Credential backend migration:[/bold] {direction_label}")
    if dry_run:
        console.print("[yellow]DRY RUN[/yellow] — no rows will be written.")

    # Read rows in batches keyed by id (stable ordering, resumable).
    where = "backend = :src"
    params: dict[str, object] = {"src": src_id}
    if tenant is not None:
        where += " AND tenant_id = :tid"
        params["tid"] = tenant
    if continue_from is not None:
        where += " AND id > :cf"
        params["cf"] = continue_from

    select_sql = (
        "SELECT id, tenant_id, provider, purpose, ciphertext_blob, nonce, auth_tag, "
        "key_version FROM tenant_credentials "
        f"WHERE {where} ORDER BY id ASC LIMIT :lim"
    )
    update_sql = (
        "UPDATE tenant_credentials SET "
        "ciphertext_blob = :blob, nonce = :nonce, auth_tag = :tag, "
        "key_version = :kv, backend = :be, updated_at = now() "
        "WHERE id = :id"
    )

    migrated = 0
    skipped = 0
    last_id = continue_from
    while True:
        with engine.connect() as conn:
            params["lim"] = batch_size
            if last_id is not None:
                params["cf"] = last_id
            rows = conn.execute(text(select_sql), params).fetchall()

        if not rows:
            break

        for row in rows:
            row_id, tenant_id, provider, purpose, ct_blob, nonce, auth_tag, key_version = row
            src_blob = EncryptedBlob(
                ciphertext=bytes(ct_blob),
                nonce=bytes(nonce),
                auth_tag=bytes(auth_tag),
                key_version=key_version,
            )
            try:
                plaintext = src_backend.decrypt(tenant_id=tenant_id, provider=provider, purpose=purpose, blob=src_blob)
            except Exception as exc:
                console.print(f"[red]decrypt failed[/red] row={row_id} tenant={tenant_id}: {exc}")
                skipped += 1
                last_id = row_id
                continue

            dst_blob = dst_backend.encrypt(tenant_id=tenant_id, provider=provider, purpose=purpose, plaintext=plaintext)

            if not dry_run:
                with engine.begin() as conn:
                    conn.execute(
                        text(update_sql),
                        {
                            "id": row_id,
                            "blob": dst_blob.ciphertext,
                            "nonce": dst_blob.nonce,
                            "tag": dst_blob.auth_tag,
                            "kv": dst_blob.key_version,
                            "be": dst_id,
                        },
                    )
            migrated += 1
            last_id = row_id

        console.print(f"[dim]checkpoint[/dim] migrated={migrated} skipped={skipped} last_id={last_id}")

    console.print(f"[green]done[/green] migrated={migrated} skipped={skipped} direction={direction_label}")
    if skipped:
        console.print(
            "[yellow]Some rows could not be decrypted (likely tampered or "
            "wrong key). They remain on the source backend; investigate or "
            "mark them invalid manually.[/yellow]"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Waitlist (cloud onboarding Variant A — manual admin approval)
# ---------------------------------------------------------------------------


def _waitlist_engine_or_exit():
    """Return SQLAlchemy engine for the cloud DB; exit 1 with a clear message
    when ENGRAMIA_DATABASE_URL is unset."""
    from sqlalchemy import create_engine

    db_url = os.environ.get("ENGRAMIA_DATABASE_URL", "").strip()
    if not db_url:
        console.print("[red]ENGRAMIA_DATABASE_URL not set[/red]")
        raise typer.Exit(1)
    return create_engine(db_url, pool_pre_ping=True)


@waitlist_app.command("list")
def waitlist_list(
    pending: bool = typer.Option(False, "--pending", help="Show only pending requests."),
    approved: bool = typer.Option(False, "--approved", help="Show only approved requests."),
    rejected: bool = typer.Option(False, "--rejected", help="Show only rejected requests."),
) -> None:
    """List waitlist requests with their status. Default: all."""
    from sqlalchemy import text

    engine = _waitlist_engine_or_exit()

    where_clauses: list[str] = []
    if pending:
        where_clauses.append("status = 'pending'")
    if approved:
        where_clauses.append("status = 'approved'")
    if rejected:
        where_clauses.append("status = 'rejected'")
    where_sql = " OR ".join(where_clauses) if where_clauses else "1=1"

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, email, name, plan_interest, country, status, "
                "created_at, tenant_id FROM waitlist_requests "
                f"WHERE {where_sql} "
                "ORDER BY created_at DESC LIMIT 200"
            )
        ).fetchall()

    if not rows:
        console.print("[green]No requests match the filter[/green]")
        return

    table = Table(title=f"Waitlist requests ({len(rows)})")
    table.add_column("id (short)", style="cyan")
    table.add_column("email")
    table.add_column("name")
    table.add_column("plan", style="bold")
    table.add_column("country")
    table.add_column("status")
    table.add_column("created")
    table.add_column("tenant")
    for r in rows:
        rid = str(r[0])
        status_color = {"pending": "yellow", "approved": "green", "rejected": "red"}.get(r[5], "white")
        table.add_row(
            rid[:8],
            str(r[1]),
            str(r[2]),
            str(r[3]),
            str(r[4]),
            f"[{status_color}]{r[5]}[/{status_color}]",
            r[6].strftime("%Y-%m-%d %H:%M") if r[6] else "—",
            (str(r[7])[:8] if r[7] else "—"),
        )
    console.print(table)
    console.print()
    console.print(
        '[yellow]Hint:[/yellow] use `engramia waitlist approve <full-id>` or `… reject <full-id> --reason "…"`.'
    )


@waitlist_app.command("approve")
def waitlist_approve(
    request_id: str = typer.Argument(..., help="Waitlist request UUID (full or unambiguous prefix)."),
    plan: str | None = typer.Option(
        None,
        "--plan",
        help="Override plan_tier. Defaults to the request's plan_interest. "
        "(developer | pro | team | business | enterprise)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without provisioning."),
) -> None:
    """Provision a cloud account from a pending waitlist request.

    Generates a one-time password, creates tenant+project+cloud_user+api_key
    via _create_registration, sets must_change_password=true, marks the
    waitlist row as approved, and emails credentials. The customer must
    change the password on first login.
    """
    import secrets

    from sqlalchemy import text

    from engramia.api.audit import AuditEvent, log_event
    from engramia.api.cloud_auth import _create_registration, _hash_password
    from engramia.email import EmailNotConfigured, send_email
    from engramia.email.templates import credentials_email

    engine = _waitlist_engine_or_exit()
    valid_plans = {"developer", "pro", "team", "business", "enterprise"}

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, email, name, plan_interest, status FROM waitlist_requests "
                "WHERE id::text = :rid OR id::text LIKE :prefix "
                "ORDER BY created_at DESC LIMIT 2"
            ),
            {"rid": request_id, "prefix": f"{request_id}%"},
        ).fetchall()

    if not row:
        console.print(f"[red]No waitlist request matching:[/red] {request_id}")
        raise typer.Exit(1)
    if len(row) > 1:
        console.print(f"[red]Ambiguous prefix '{request_id}' matched multiple rows. Use the full UUID.[/red]")
        raise typer.Exit(1)

    full_id, email, name, plan_interest, current_status = (
        str(row[0][0]),
        str(row[0][1]),
        str(row[0][2]),
        str(row[0][3]),
        str(row[0][4]),
    )

    if current_status != "pending":
        console.print(f"[red]Cannot approve — request is already {current_status}.[/red]")
        raise typer.Exit(1)

    target_plan = (plan or plan_interest).lower()
    if target_plan not in valid_plans:
        console.print(f"[red]Invalid plan:[/red] {target_plan}")
        raise typer.Exit(1)

    if dry_run:
        console.print("[yellow]DRY-RUN[/yellow] Would provision:")
        console.print(f"  email      : {email}")
        console.print(f"  name       : {name}")
        console.print(f"  plan       : {target_plan}")
        console.print("  password   : (would be auto-generated, 16 chars)")
        return

    one_time_password = secrets.token_urlsafe(16)
    password_hash = _hash_password(one_time_password)

    result = _create_registration(
        engine,
        email=email,
        password_hash=password_hash,
        name=name,
        provider="credentials",
        provider_id=None,
        email_verified=True,
    )

    with engine.begin() as conn:
        if target_plan != "developer":
            conn.execute(
                text("UPDATE tenants SET plan_tier = :plan WHERE id = :tid"),
                {"plan": target_plan, "tid": result["tenant_id"]},
            )
        conn.execute(
            text("UPDATE cloud_users SET must_change_password = true WHERE id = :uid"),
            {"uid": result["user_id"]},
        )
        conn.execute(
            text(
                "UPDATE waitlist_requests SET status='approved', approved_at=now(), "
                "tenant_id = :tid WHERE id::text = :rid"
            ),
            {"tid": result["tenant_id"], "rid": full_id},
        )

    log_event(
        AuditEvent.WAITLIST_APPROVED,
        request_id=full_id,
        tenant_id=result["tenant_id"],
        plan=target_plan,
    )

    dashboard_url = os.environ.get("ENGRAMIA_DASHBOARD_URL", "https://app.engramia.dev").strip().rstrip("/")
    try:
        subj, txt, html = credentials_email(
            recipient_name=name,
            login_email=email,
            one_time_password=one_time_password,
            dashboard_url=dashboard_url,
            plan_tier=target_plan,
        )
        send_email(to=email, subject=subj, html=html, text=txt)
        email_status = "sent"
    except EmailNotConfigured:
        email_status = "skipped (SMTP not configured)"
    except Exception as exc:
        email_status = f"failed: {exc}"

    console.print()
    console.print(f"[green]Approved[/green] request {full_id[:8]}")
    console.print(f"  email      : {email}")
    console.print(
        f"  password   : [bold]{one_time_password}[/bold] (one-time — customer forced to change on first login)"
    )
    console.print(f"  plan       : {target_plan}")
    console.print(f"  tenant_id  : {result['tenant_id']}")
    console.print(f"  api_key    : [bold]{result['api_key']}[/bold]")
    console.print(f"  email      : {email_status}")


@waitlist_app.command("reject")
def waitlist_reject(
    request_id: str = typer.Argument(..., help="Waitlist request UUID (full or unambiguous prefix)."),
    reason: str = typer.Option(
        ...,
        "--reason",
        help="Free-text reason — interpolated into the rejection email. Draft "
        "the wording out-of-band (Claude works well as a co-writer).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the rendered rejection email without sending."),
) -> None:
    """Reject a pending waitlist request and send the customer a polite email."""
    from sqlalchemy import text

    from engramia.api.audit import AuditEvent, log_event
    from engramia.email import EmailNotConfigured, send_email
    from engramia.email.templates import waitlist_rejection_email

    engine = _waitlist_engine_or_exit()

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, email, name, status FROM waitlist_requests "
                "WHERE id::text = :rid OR id::text LIKE :prefix "
                "ORDER BY created_at DESC LIMIT 2"
            ),
            {"rid": request_id, "prefix": f"{request_id}%"},
        ).fetchall()

    if not row:
        console.print(f"[red]No waitlist request matching:[/red] {request_id}")
        raise typer.Exit(1)
    if len(row) > 1:
        console.print(f"[red]Ambiguous prefix '{request_id}' — use the full UUID.[/red]")
        raise typer.Exit(1)

    full_id, email, name, current_status = (
        str(row[0][0]),
        str(row[0][1]),
        str(row[0][2]),
        str(row[0][3]),
    )

    if current_status != "pending":
        console.print(f"[red]Cannot reject — request is already {current_status}.[/red]")
        raise typer.Exit(1)

    subj, txt, html = waitlist_rejection_email(recipient_name=name, reason=reason)

    if dry_run:
        console.print("[yellow]DRY-RUN[/yellow] Would send:")
        console.print(f"  to      : {email}")
        console.print(f"  subject : {subj}")
        console.print()
        console.print(txt)
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE waitlist_requests SET status='rejected', "
                "rejected_at=now(), rejection_reason=:reason "
                "WHERE id::text = :rid"
            ),
            {"reason": reason, "rid": full_id},
        )

    log_event(AuditEvent.WAITLIST_REJECTED, request_id=full_id)

    try:
        send_email(to=email, subject=subj, html=html, text=txt)
        email_status = "sent"
    except EmailNotConfigured:
        email_status = "skipped (SMTP not configured)"
    except Exception as exc:
        email_status = f"failed: {exc}"

    console.print()
    console.print(f"[red]Rejected[/red] request {full_id[:8]}")
    console.print(f"  email      : {email}")
    console.print(f"  notify     : {email_status}")


@waitlist_app.command("export")
def waitlist_export(
    since: str | None = typer.Option(
        None, "--since", help="ISO date — include only requests created on/after this date (e.g. 2026-04-01)."
    ),
    output: str | None = typer.Option(None, "--output", help="Write to file instead of stdout."),
) -> None:
    """Export waitlist rows as CSV — for hand-off / backup / analytics."""
    import csv
    import sys

    from sqlalchemy import text

    engine = _waitlist_engine_or_exit()

    where_sql = "1=1"
    params: dict = {}
    if since:
        where_sql = "created_at >= :since"
        params["since"] = since

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, email, name, plan_interest, country, use_case, "
                "company_name, referral_source, status, rejection_reason, "
                "tenant_id, created_at, approved_at, rejected_at "
                "FROM waitlist_requests "
                f"WHERE {where_sql} ORDER BY created_at DESC"
            ),
            params,
        ).fetchall()

    fieldnames = [
        "id",
        "email",
        "name",
        "plan_interest",
        "country",
        "use_case",
        "company_name",
        "referral_source",
        "status",
        "rejection_reason",
        "tenant_id",
        "created_at",
        "approved_at",
        "rejected_at",
    ]

    def _write(stream) -> None:
        writer = csv.writer(stream)
        writer.writerow(fieldnames)
        for r in rows:
            writer.writerow([str(c) if c is not None else "" for c in r])

    if output:
        with open(output, "w", newline="", encoding="utf-8") as fh:
            _write(fh)
        console.print(f"[green]Exported {len(rows)} rows[/green] → {output}")
    else:
        _write(sys.stdout)


def main() -> None:
    """Entry point for ``engramia`` CLI command."""
    logging.basicConfig(level=logging.WARNING)
    app()


if __name__ == "__main__":
    main()
