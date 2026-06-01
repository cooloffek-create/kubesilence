"""KubeSilence CLI — fully wired analyze, silence, and configure commands."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, cast

import typer
from rich.console import Console
from rich.table import Table

from kubesilence import __version__

# ---------------------------------------------------------------------------
# Lazy imports — deferred so --version and --help stay fast
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="kubesilence",
    help="AlertOps-Reducer — fight alert fatigue.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Callback: --version
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def version_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit."),
) -> None:
    if version:
        console.print(f"[bold]KubeSilence[/bold] v{__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Config path helpers
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(os.getenv("KUBESILENCE_CONFIG_DIR", Path.home() / ".config" / "kubesilence"))
_CONFIG_FILE = _CONFIG_DIR / ".env"


def _provider_label(provider: str) -> str:
    labels = {"mock": "Mock (static fixtures)", "opsgenie": "Opsgenie", "datadog": "Datadog"}
    return labels.get(provider, provider.capitalize())


# ---------------------------------------------------------------------------
# Provider resolver
# ---------------------------------------------------------------------------


def _resolve_provider(provider: str):
    """Return a ``BaseAlertProvider`` instance for *provider*."""
    from kubesilence.providers.mock import MockAlertProvider

    prov_map = {
        "mock": lambda: MockAlertProvider(),
        "opsgenie": lambda: _load_opsgenie(),
        "datadog": lambda: _load_datadog(),
    }
    creator = prov_map.get(provider)
    if creator is None:
        available = ", ".join(prov_map)
        err_console.print(
            f"[red]✗[/red] Unknown provider [bold]{provider}[/bold]. Available: {available}"
        )
        raise typer.Exit(code=1)
    return creator()


def _load_opsgenie():
    from kubesilence.providers.opsgenie import OpsgenieProvider

    api_key = _read_config("OPSGENIE_API_KEY")
    return OpsgenieProvider(api_key=api_key)


def _load_datadog():
    from kubesilence.providers.datadog import DatadogProvider

    api_key = _read_config("DATADOG_API_KEY")
    app_key = _read_config("DATADOG_APP_KEY")
    return DatadogProvider(api_key=api_key, app_key=app_key)


# ---------------------------------------------------------------------------
# Config read / write
# ---------------------------------------------------------------------------


def _read_config(key: str) -> str:
    """Read *key* from the config file or environment."""
    val = os.environ.get(key) or _dotenv_get(key)
    if val:
        return val
    err_console.print(
        f"[red]✗[/red] {key} not configured. Run [bold]kubesilence configure[/bold] first."
    )
    raise typer.Exit(code=1)


def _dotenv_get(key: str) -> str | None:
    if not _CONFIG_FILE.exists():
        return None
    prefix = f"{key}="
    for line in _CONFIG_FILE.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip("\"'")
    return None


def _dotenv_set(key: str, value: str) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    found = False
    if _CONFIG_FILE.exists():
        lines = _CONFIG_FILE.read_text().splitlines()
        new_lines: list[str] = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f'{key}="{value}"')
                found = True
            else:
                new_lines.append(line)
        lines = new_lines
    if not found:
        lines.append(f'{key}="{value}"')
    _CONFIG_FILE.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# analyze command
# ---------------------------------------------------------------------------


@app.command()
def analyze(
    provider: str = typer.Argument("mock", help="Alert provider: mock, opsgenie, datadog"),
    days: int = typer.Option(7, "--days", "-d", help="Look-back window in days.", min=1, max=366),
    threshold: int = typer.Option(
        85, "--threshold", "-t", help="Similarity threshold (0-100).", min=0, max=100
    ),
    window: int = typer.Option(60, "--window", "-w", help="Dedup time window in seconds.", min=1),
) -> None:
    """Fetch and analyze alerts from *provider*."""
    prov = _resolve_provider(provider)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    with console.status(f"[bold green]Fetching alerts from {_provider_label(provider)}…"):
        loop = asyncio.new_event_loop()
        raw = loop.run_until_complete(_collect_alerts(prov, start, end))
        loop.close()

    if not raw:
        console.print("[yellow]⚠[/yellow] No alerts found in the window.")
        raise typer.Exit()

    # Parse and run analytics
    with console.status("[bold green]Running analytics engine…") as _:
        from kubesilence.analytics.parser import parse_alerts, ProviderName
        from kubesilence.analytics.deduplication import cluster_duplicates
        from kubesilence.analytics.cascade import detect_cascades

        # Parse to unified DataFrame
        df = parse_alerts(raw, provider=cast("ProviderName", provider))

        # Dedup — needs raw dicts with createdAt
        dicts = df.to_dict(orient="records")
        for d in dicts:
            ts = d.pop("created_at")
            d["createdAt"] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        clusters = cluster_duplicates(dicts, time_window_sec=window, threshold=threshold)
        cascades = detect_cascades(dicts, window_sec=window * 5)

    # ── Summary table ──
    overview = Table(title="Alert Noise Overview", show_header=True)
    overview.add_column("Metric", style="cyan")
    overview.add_column("Value", style="bold magenta")

    total = len(raw)
    dup_count = len(clusters)
    cascade_count = len(cascades)
    dup_alert_count = sum(len(c) for c in clusters)
    noisy_alerts = dup_alert_count + sum(
        len(c["alerts"]) - 1
        for c in cascades  # exclude root cause
    )

    overview.add_row("Total alerts", str(total))
    overview.add_row("Duplicate clusters", str(dup_count))
    overview.add_row("Alerts in duplicates", str(dup_alert_count))
    overview.add_row("Cascades detected", str(cascade_count))
    overview.add_row("Noise reduction potential", f"{noisy_alerts}/{total}")
    overview.add_row("Noise ratio", f"{noisy_alerts / max(total, 1) * 100:.0f}%")
    console.print()
    console.print(overview)

    # ── Duplicate clusters table ──
    if clusters:
        dup_table = Table(title="Duplicate Clusters", show_header=True)
        dup_table.add_column("Cluster", style="yellow")
        dup_table.add_column("Alert IDs", style="cyan")
        dup_table.add_column("Message snippet", style="white", no_wrap=False)
        dup_table.add_column("Time span", style="dim")
        for i, cluster in enumerate(clusters[:10]):  # show top 10
            cluster_alerts = [dicts[idx] for idx in cluster]
            ids = ", ".join(a.get("id", "#?") for a in cluster_alerts)
            snippet = cluster_alerts[0].get("message", "")[:60]
            ts0 = cluster_alerts[0].get("createdAt", "")
            ts1 = cluster_alerts[-1].get("createdAt", "")
            span = f"{ts0[11:19]} → {ts1[11:19]}" if ts0 and ts1 else ""
            dup_table.add_row(f"#{i + 1}", ids, snippet, span)
        console.print()
        console.print(dup_table)
        if len(clusters) > 10:
            console.print(f"[dim]… and {len(clusters) - 10} more clusters[/dim]")

    # ── Cascade table ──
    if cascades:
        cas_table = Table(title="Cascades / Alert Storms", show_header=True)
        cas_table.add_column("Cascade", style="yellow")
        cas_table.add_column("Services", style="cyan")
        cas_table.add_column("Alert count", style="magenta")
        cas_table.add_column("Root cause", style="green")
        cas_table.add_column("Time span", style="dim")
        for i, cascade in enumerate(cascades):
            services = ", ".join(cascade.get("services", []))
            alert_count = len(cascade.get("alerts", []))
            root_idx = cascade.get("root_cause_suspect", 0)
            root_msg = dicts[root_idx].get("message", "")[:50] if root_idx < len(dicts) else ""
            span = f"{cascade.get('start_time', '')[11:19]} → {cascade.get('end_time', '')[11:19]}"
            cas_table.add_row(f"#{i + 1}", services, str(alert_count), root_msg, span)
        console.print()
        console.print(cas_table)


async def _collect_alerts(provider, start, end):
    """Collect all alerts from an async generator into a list."""
    return [a async for a in provider.get_alerts(start, end)]


# ---------------------------------------------------------------------------
# remediate command
# ---------------------------------------------------------------------------


@app.command()
def remediate(
    provider: str = typer.Argument("mock", help="Alert provider: mock, opsgenie, datadog"),
    days: int = typer.Option(7, "--days", "-d", help="Look-back window in days.", min=1, max=366),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt and apply all."),
) -> None:
    """Analyze and interactively silence noisy alerts."""
    prov = _resolve_provider(provider)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    # 1. Fetch
    with console.status("[bold green]Fetching alerts…") as _:
        loop = asyncio.new_event_loop()
        raw = loop.run_until_complete(_collect_alerts(prov, start, end))
        loop.close()

    if not raw:
        console.print("[yellow]⚠[/yellow] No alerts found.")
        raise typer.Exit()

    # 2. Analyze
    from kubesilence.analytics.cascade import detect_cascades
    from kubesilence.analytics.deduplication import cluster_duplicates

    dicts = list(raw)
    clusters = cluster_duplicates(dicts, time_window_sec=60)
    cascades = detect_cascades(dicts)

    if not clusters and not cascades:
        console.print("[green]✓[/green] No noisy alerts to remediate. All clear!")
        raise typer.Exit()

    # 3. Build remediation plan
    from kubesilence.remediation.engine import RemediationEngine
    from kubesilence.remediation.schema import SilenceRequest

    engine = RemediationEngine(prov, dry_run=True)

    plan: list[SilenceRequest] = []

    for cluster in clusters:
        ids = [dicts[i].get("id", str(i)) for i in cluster]
        plan.append(
            SilenceRequest(
                alert_ids=ids,
                reason="Auto-silenced — duplicate alert cluster",
                source="dedup",
            )
        )

    for cascade in cascades:
        ids = [dicts[i].get("id", str(i)) for i in cascade["alerts"]]
        plan.append(
            SilenceRequest(
                alert_ids=ids,
                reason=f"Auto-silenced — cascade root suspect: {cascade.get('root_cause_suspect')}",
                source="cascade",
            )
        )

    # 4. Show plan
    console.print()
    plan_table = Table(title="Remediation Plan (DRY-RUN)", show_header=True)
    plan_table.add_column("#", style="yellow")
    plan_table.add_column("Source", style="cyan")
    plan_table.add_column("Alert IDs", style="white")
    plan_table.add_column("Reason", style="dim", no_wrap=False)
    for i, req in enumerate(plan):
        plan_table.add_row(
            str(i + 1),
            req.source,
            ", ".join(req.alert_ids),
            req.reason[:60],
        )
    console.print(plan_table)
    console.print(f"\n[bold]{len(plan)}[/bold] silence action(s) proposed.")

    # 5. Confirm
    if not yes:
        confirmed = typer.confirm(
            "\nApply these silence rules? ([bold red]This will mute alerts![/bold red])",
            default=False,
        )
        if not confirmed:
            console.print("[yellow]✗[/yellow] Aborted — no changes made.")
            raise typer.Exit()

    # 6. Execute (dry_run=False)
    engine.dry_run = False
    results: list[dict] = []
    with console.status("[bold green]Applying silence rules…") as _:
        loop = asyncio.new_event_loop()
        for req in plan:
            resp = loop.run_until_complete(engine.silence_request(req))
            results.append(resp)
        loop.close()

    success = sum(1 for r in results if r.get("status") in ("success", "simulated"))
    console.print(f"\n[green]✓[/green] {success}/{len(plan)} silence rule(s) applied successfully.")


# ---------------------------------------------------------------------------
# configure command
# ---------------------------------------------------------------------------


@app.command()
def configure(
    provider: str = typer.Argument(..., help="Provider to configure: opsgenie, datadog"),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", help="API key (omit for prompt)."
    ),
    app_key: Optional[str] = typer.Option(
        None, "--app-key", "-a", help="Datadog App key (only needed for datadog)."
    ),
) -> None:
    """Save API credentials for *provider* to the config file.

    Credentials are stored in ``~/.config/kubesilence/.env``
    (or ``$KUBESILENCE_CONFIG_DIR/.env``).
    """
    provider = provider.lower().strip()
    if provider == "opsgenie":
        key = api_key or typer.prompt("Opsgenie API key", hide_input=True)
        _dotenv_set("OPSGENIE_API_KEY", key)
        console.print(f"[green]✓[/green] Opsgenie credentials saved to [bold]{_CONFIG_FILE}[/bold]")
    elif provider == "datadog":
        key = api_key or typer.prompt("Datadog API key", hide_input=True)
        ak = app_key or typer.prompt("Datadog App key", hide_input=True)
        _dotenv_set("DATADOG_API_KEY", key)
        _dotenv_set("DATADOG_APP_KEY", ak)
        console.print(f"[green]✓[/green] Datadog credentials saved to [bold]{_CONFIG_FILE}[/bold]")
    else:
        err_console.print(
            f"[red]✗[/red] Unknown provider [bold]{provider}[/bold]. Supported: opsgenie, datadog"
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    app()
