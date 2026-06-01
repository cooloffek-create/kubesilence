"""Tests for alert providers (base, mock, opsgenie, datadog)."""

from datetime import datetime, timedelta

import pytest

from kubesilence.providers.base import AlertRecord, BaseAlertProvider
from kubesilence.providers.mock import FIXTURE_ALERTS, MockAlertProvider
from kubesilence.providers.opsgenie import OpsgenieProvider

# ──────────────────────────────────────────────────────────────────────
# MockAlertProvider
# ──────────────────────────────────────────────────────────────────────


class TestMockAlertProvider:
    @pytest.mark.asyncio
    async def test_yields_filtered_by_date_range(self):
        """Only alerts within [start, end) are returned."""
        provider = MockAlertProvider()
        start = datetime(2025, 6, 1, 10, 0, 0)  # includes alert-001
        end = datetime(2025, 6, 1, 10, 0, 15)  # cuts before alert-002
        results: list[AlertRecord] = []
        async for a in provider.get_alerts(start, end):
            results.append(a)
        assert len(results) == 1
        assert results[0]["id"] == "alert-001"

    @pytest.mark.asyncio
    async def test_yields_nothing_outside_range(self):
        provider = MockAlertProvider()
        results: list[AlertRecord] = []
        async for a in provider.get_alerts(datetime(2024, 1, 1), datetime(2024, 12, 31)):
            results.append(a)
        assert results == []

    @pytest.mark.asyncio
    async def test_yields_all_alerts_in_wide_window(self):
        provider = MockAlertProvider()
        start = datetime(2025, 6, 1, 10, 0, 0)
        end = datetime(2025, 6, 1, 12, 0, 0)
        results: list[AlertRecord] = []
        async for a in provider.get_alerts(start, end):
            results.append(a)
        assert len(results) == 10  # all 10 fixture alerts

    @pytest.mark.asyncio
    async def test_create_silence_returns_success(self):
        provider = MockAlertProvider()
        result = await provider.create_silence(["alert-001"], "test reason")
        assert result["status"] == "success"
        assert result["silenced_ids"] == ["alert-001"]

    @pytest.mark.asyncio
    async def test_custom_alert_list(self):
        custom = [{"id": "custom-1", "createdAt": "2025-06-01T10:00:00Z", "message": "custom"}]
        provider = MockAlertProvider(alerts=custom)
        results: list[AlertRecord] = []
        async for a in provider.get_alerts(datetime(2025, 6, 1), datetime(2025, 6, 2)):
            results.append(a)
        assert len(results) == 1
        assert results[0]["id"] == "custom-1"

    # ── convenience accessors ──

    def test_duplicate_alerts_property(self):
        provider = MockAlertProvider()
        dups = provider.duplicate_alerts
        assert len(dups) == 2
        assert all(a["id"].startswith("alert-00") for a in dups)

    def test_cascade_alerts_property(self):
        provider = MockAlertProvider()
        cascade = provider.cascade_alerts
        assert len(cascade) == 3  # DB + Gateway + ELB
        services = {a["tags"]["service"] for a in cascade}
        assert services == {"database", "gateway"}

    def test_solitary_alerts_property(self):
        provider = MockAlertProvider()
        solo = provider.solitary_alerts
        assert len(solo) == 1
        assert solo[0]["id"] == "alert-008"

    def test_fixture_count(self):
        assert len(FIXTURE_ALERTS) == 10


# ──────────────────────────────────────────────────────────────────────
# OpsgenieProvider
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_opsgenie_provider_initialization():
    provider = OpsgenieProvider(api_key="test-key")
    assert provider._api_key == "test-key"


@pytest.mark.asyncio
async def test_opsgenie_time_chunking():
    """Verify day-sized chunking over a 3-day window."""
    provider = OpsgenieProvider(api_key="test")
    start = datetime(2025, 1, 1)
    end = datetime(2025, 1, 4)
    chunks = provider._chunk_window(start, end)
    assert len(chunks) == 3
    for chunk_start, chunk_end in chunks:
        assert (chunk_end - chunk_start).days == 1


@pytest.mark.asyncio
async def test_opsgenie_get_alerts_empty():
    provider = OpsgenieProvider(api_key="test")
    now = datetime.utcnow()
    alerts: list[AlertRecord] = []
    async for alert in provider.get_alerts(now - timedelta(hours=1), now):
        alerts.append(alert)
    assert alerts == []


# ──────────────────────────────────────────────────────────────────────
# BaseAlertProvider
# ──────────────────────────────────────────────────────────────────────


class TestBaseAlertProvider:
    def test_base_is_abstract(self):
        """BaseAlertProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseAlertProvider()  # type: ignore
