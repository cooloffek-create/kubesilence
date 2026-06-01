"""MockAlertProvider — static JSON data for local offline testing.

Provides a full set of realistic alert fixtures so the analytics
engine, remediation engine, and CLI can all be exercised without
live API credentials.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncGenerator

from kubesilence.providers.base import AlertRecord, BaseAlertProvider

# ──────────────────────────────────────────────────────────────────────
# Static alert fixture data
# ──────────────────────────────────────────────────────────────────────
# Each alert has real-world fields that exercise every analytics path:
#   • Duplicate CPU alerts (same message, 15-45s apart)
#   • Near-duplicate memory alerts (same topic, slightly different wording)
#   • Cross-service cascade (DB latency → 502 errors on API gateway)
#   • Distant single alerts (outside any window — should go unclustered)
#   • Disk alerts on a different service (different message, diff service)
# ──────────────────────────────────────────────────────────────────────
# All timestamps are ISO-8601 in UTC, anchored to a base time so the
# provider can filter by start_date/end_date on the fly.

_BASE_TS = "2025-06-01T10:00:00Z"

FIXTURE_ALERTS: list[dict[str, Any]] = [
    # ── Duplicate pair: same CPU message, 30s apart ──
    {
        "id": "alert-001",
        "createdAt": "2025-06-01T10:00:00Z",
        "message": "CPU usage exceeded 90% on instance i-0abcd1234efgh5678",
        "description": "High CPU utilization detected on prod instance",
        "source": "CloudWatch",
        "priority": "P2",
        "tags": {"service": "compute", "env": "prod", "region": "us-east-1"},
        "metadata": {"instance_id": "i-0abcd1234efgh5678", "threshold": "90"},
    },
    {
        "id": "alert-002",
        "createdAt": "2025-06-01T10:00:30Z",
        "message": "CPU usage exceeded 90% on instance i-0abcd1234efgh5678",
        "description": "High CPU utilization detected on prod instance",
        "source": "CloudWatch",
        "priority": "P2",
        "tags": {"service": "compute", "env": "prod", "region": "us-east-1"},
        "metadata": {"instance_id": "i-0abcd1234efgh5678", "threshold": "90"},
    },
    # ── Third CPU alert from a different instance (similar but not identical) ──
    {
        "id": "alert-003",
        "createdAt": "2025-06-01T10:01:00Z",
        "message": "CPU usage exceeded 95% on instance i-0wxyz9876stuv4321",
        "description": "High CPU utilization detected on prod instance",
        "source": "CloudWatch",
        "priority": "P1",
        "tags": {"service": "compute", "env": "prod", "region": "us-west-2"},
        "metadata": {"instance_id": "i-0wxyz9876stuv4321", "threshold": "95"},
    },
    # ── Memory pressure alert (near-duplicate wording to CPU, different metric) ──
    {
        "id": "alert-004",
        "createdAt": "2025-06-01T10:01:15Z",
        "message": "Memory usage exceeded 90% on instance i-0abcd1234efgh5678",
        "description": "High memory utilization detected on prod instance",
        "source": "CloudWatch",
        "priority": "P2",
        "tags": {"service": "compute", "env": "prod", "region": "us-east-1"},
        "metadata": {"instance_id": "i-0abcd1234efgh5678", "threshold": "90"},
    },
    # ── Database latency alert (starts a cascade scenario) ──
    {
        "id": "alert-005",
        "createdAt": "2025-06-01T10:02:00Z",
        "message": "Database replication lag exceeds 120s on primary-db-01",
        "description": "PostgreSQL replication lag threshold breached",
        "source": "Datadog",
        "priority": "P1",
        "tags": {"service": "database", "env": "prod", "component": "postgres"},
        "metadata": {"db_instance": "primary-db-01", "lag_seconds": 125},
    },
    # ── API gateway 502 errors (cascade — likely downstream of DB latency) ──
    {
        "id": "alert-006",
        "createdAt": "2025-06-01T10:03:30Z",
        "message": "HTTP 502 error rate > 5% on api-gateway-prod",
        "description": "Upstream failure causing 502 responses on API gateway",
        "source": "Datadog",
        "priority": "P1",
        "tags": {"service": "gateway", "env": "prod", "component": "nginx"},
        "metadata": {"gateway": "api-gateway-prod", "error_rate": 7.2},
    },
    # ── Disk space alert on storage service (different service, later timestamp) ──
    {
        "id": "alert-007",
        "createdAt": "2025-06-01T10:05:00Z",
        "message": "Disk space usage at 96% on volume vol-abcdef01",
        "description": "Disk space critically low on storage node",
        "source": "CloudWatch",
        "priority": "P2",
        "tags": {"service": "storage", "env": "prod", "region": "eu-west-1"},
        "metadata": {"volume_id": "vol-abcdef01", "usage_pct": 96},
    },
    # ── Distant single alert (outside any cascade/dedup window) ──
    {
        "id": "alert-008",
        "createdAt": "2025-06-01T11:00:00Z",
        "message": "SSL certificate for *.example.com expires in 7 days",
        "description": "Certificate expiry reminder",
        "source": "AlertManager",
        "priority": "P3",
        "tags": {"service": "security", "env": "prod"},
        "metadata": {"domain": "*.example.com", "days_remaining": 7},
    },
    # ── Exact duplicate of alert-008 (tests dedup across hour boundary logic) ──
    {
        "id": "alert-009",
        "createdAt": "2025-06-01T11:00:30Z",
        "message": "SSL certificate for *.example.com expires in 7 days",
        "description": "Certificate expiry reminder",
        "source": "AlertManager",
        "priority": "P3",
        "tags": {"service": "security", "env": "prod"},
        "metadata": {"domain": "*.example.com", "days_remaining": 7},
    },
    # ── Load balancer alert (tests tags-based cascade grouping) ──
    {
        "id": "alert-010",
        "createdAt": "2025-06-01T10:02:30Z",
        "message": "ELB healthy host count dropped to 1 for api-gateway-prod",
        "description": "Load balancer target count critically low",
        "source": "CloudWatch",
        "priority": "P1",
        "tags": {"service": "gateway", "env": "prod", "component": "elb"},
        "metadata": {"elb_name": "api-gateway-prod", "healthy_hosts": 1},
    },
]


class MockAlertProvider(BaseAlertProvider):
    """Returns static fixture alerts for offline dev / testing.

    Filters by *start_date* / *end_date* so it behaves like a real
    provider.  Useful for:

    - Running the analytics engine without API keys
    - Testing the CLI workflow end-to-end
    - CI pipelines that shouldn't make external network calls
    - Reproducing specific alert scenarios in unit tests
    """

    def __init__(self, alerts: list[dict[str, Any]] | None = None) -> None:
        self.alerts = alerts or FIXTURE_ALERTS

    async def get_alerts(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> AsyncGenerator[AlertRecord, None]:
        """Yield fixture alerts whose ``createdAt`` falls in [start, end)."""
        start_ts = start_date.isoformat()
        end_ts = end_date.isoformat()
        for alert in self.alerts:
            ts = alert["createdAt"]
            if start_ts <= ts < end_ts:
                yield AlertRecord(alert)

    async def create_silence(self, alert_ids: list[str], reason: str) -> dict[str, Any]:
        """Simulate a silence creation — always succeeds."""
        return {
            "status": "success",
            "provider": "mock",
            "silenced_ids": alert_ids,
            "reason": reason,
        }

    # ──────────────────────────────────────────────────────────────────
    # Convenience accessors for tests
    # ──────────────────────────────────────────────────────────────────

    @property
    def duplicate_alerts(self) -> list[dict[str, Any]]:
        """Alerts that should cluster as duplicates (CPU pair)."""
        return [a for a in self.alerts if a["id"] in ("alert-001", "alert-002")]

    @property
    def cascade_alerts(self) -> list[dict[str, Any]]:
        """Alerts involved in the DB → Gateway cascade."""
        return [a for a in self.alerts if a["id"] in ("alert-005", "alert-006", "alert-010")]

    @property
    def solitary_alerts(self) -> list[dict[str, Any]]:
        """Alerts far from any cluster (should remain solo)."""
        return [a for a in self.alerts if a["id"] == "alert-008"]
