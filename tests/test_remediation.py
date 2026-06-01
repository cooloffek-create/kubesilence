"""Tests for remediation engine, SilenceRequest, and dry-run safety layer."""

import pytest

from kubesilence.providers.mock import MockAlertProvider
from kubesilence.providers.opsgenie import OpsgenieProvider
from kubesilence.remediation.engine import RemediationEngine
from kubesilence.remediation.schema import SilenceRequest

# ===================================================================
# SilenceRequest schema
# ===================================================================


class TestSilenceRequest:
    def test_minimal_creation(self):
        req = SilenceRequest(alert_ids=["a1", "a2"], reason="test")
        assert req.alert_ids == ["a1", "a2"]
        assert req.reason == "test"
        assert req.source == "manual"
        assert req.dry_run is False

    def test_dedup_source(self):
        req = SilenceRequest(
            alert_ids=["a1"],
            reason="duplicate cpu alert",
            source="dedup",
        )
        assert req.source == "dedup"

    def test_cascade_source(self):
        req = SilenceRequest(
            alert_ids=["a5", "a6", "a10"],
            reason="cascade root suspect",
            source="cascade",
        )
        assert req.source == "cascade"

    def test_dry_run_flag(self):
        req = SilenceRequest(alert_ids=[], reason="", dry_run=True)
        assert req.dry_run is True

    def test_cluster_metadata(self):
        req = SilenceRequest(
            alert_ids=["a1", "a2"],
            reason="dedup",
            source="dedup",
            cluster_metadata={"similarity": 92.5, "time_window": 60},
        )
        assert req.cluster_metadata["similarity"] == 92.5

    def test_generic_payload(self):
        req = SilenceRequest(alert_ids=["a1"], reason="test")
        payload = req.to_provider_payload("generic")
        assert payload["silenced_ids"] == ["a1"]
        assert payload["reason"] == "test"

    def test_opsgenie_payload(self):
        req = SilenceRequest(alert_ids=["a1", "a2"], reason="dedup", source="dedup")
        payload = req.to_provider_payload("opsgenie")
        assert "filter" in payload
        assert payload["filter"]["condition"] == 'id = "a1" OR id = "a2"'
        assert payload["enabled"] is True
        assert payload["reason"] == "dedup"

    def test_opsgenie_dry_payload_disabled(self):
        req = SilenceRequest(alert_ids=["a1"], reason="test", dry_run=True)
        payload = req.to_provider_payload("opsgenie")
        assert payload["enabled"] is False

    def test_datadog_payload(self):
        req = SilenceRequest(alert_ids=["a1"], reason="test")
        payload = req.to_provider_payload("datadog")
        assert "scope" in payload
        assert payload["message"] == "test"
        assert payload["active"] is True

    def test_dry_run_summary_output(self):
        req = SilenceRequest(alert_ids=["a1", "a2"], reason="test", source="dedup")
        summary = req.dry_run_summary()
        assert "Dry-Run" in summary
        assert "dedup" in summary
        assert "a1, a2" in summary


# ===================================================================
# RemediationEngine — existing behaviour
# ===================================================================


@pytest.mark.asyncio
async def test_silence_duplicates_default():
    provider = OpsgenieProvider(api_key="test")
    engine = RemediationEngine(provider, dry_run=False)
    alerts = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
    results = await engine.silence_duplicates(
        [[0, 1], [2]],
        alerts,
        reason="test",
    )
    assert len(results) == 2
    assert results[0]["silenced_ids"] == ["a1", "a2"]


# ===================================================================
# Dry-run safety layer
# ===================================================================


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_payload_not_executed(self):
        """When dry_run=True, provider.create_silence is never called."""
        provider = MockAlertProvider()
        engine = RemediationEngine(provider, dry_run=True)
        alerts = [{"id": "a1"}, {"id": "a2"}]
        results = await engine.silence_duplicates(
            [[0, 1]],
            alerts,
            reason="dry test",
        )
        assert len(results) == 1
        assert results[0]["dry_run"] is True
        assert "payload" in results[0]
        assert "summary" in results[0]

    @pytest.mark.asyncio
    async def test_dry_run_payload_has_correct_ids(self):
        provider = MockAlertProvider()
        engine = RemediationEngine(provider, dry_run=True)
        alerts = [{"id": "alert-001"}, {"id": "alert-002"}]
        results = await engine.silence_duplicates(
            [[0, 1]],
            alerts,
            reason="dry test",
        )
        payload = results[0]["payload"]
        assert payload["silenced_ids"] == ["alert-001", "alert-002"]

    @pytest.mark.asyncio
    async def test_dry_run_can_be_toggled(self):
        provider = MockAlertProvider()
        engine = RemediationEngine(provider, dry_run=True)
        assert engine.dry_run is True
        engine.dry_run = False
        assert engine.dry_run is False

    def test_build_payloads_local_only(self):
        """build_payloads is always local — no provider interaction."""
        provider = MockAlertProvider()
        engine = RemediationEngine(provider, dry_run=True)
        alerts = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
        payloads = engine.build_payloads(
            [[0, 1], [2]],
            alerts,
            reason="preview",
        )
        assert len(payloads) == 2
        assert payloads[0]["silenced_ids"] == ["a1", "a2"]

    @pytest.mark.asyncio
    async def test_silence_request_prebuilt(self):
        """silence_request() can take a pre-built SilenceRequest."""
        provider = MockAlertProvider()
        engine = RemediationEngine(provider, dry_run=False)
        req = SilenceRequest(
            alert_ids=["a1", "a2"],
            reason="pre-built",
            source="manual",
        )
        result = await engine.silence_request(req)
        assert result.get("silenced_ids") == ["a1", "a2"]

    @pytest.mark.asyncio
    async def test_silence_request_dry_run_prebuilt(self):
        provider = MockAlertProvider()
        engine = RemediationEngine(provider, dry_run=False)
        req = SilenceRequest(
            alert_ids=["a1", "a2"],
            reason="pre-built dry",
            dry_run=True,  # request-level dry_run overrides engine
        )
        result = await engine.silence_request(req)
        assert result["dry_run"] is True
        assert "payload" in result

    @pytest.mark.asyncio
    async def test_mock_provider_dedup_silence(self):
        """End-to-end: MockProvider dedup clusters → dry-run preview."""
        provider = MockAlertProvider()
        engine = RemediationEngine(provider, dry_run=True)
        alerts = provider.alerts
        clusters = [[0, 1]]  # alert-001 + alert-002
        results = await engine.silence_duplicates(
            clusters,
            alerts,
            reason="dup cpu alerts",
            source="dedup",
        )
        assert len(results) == 1
        payload = results[0]["payload"]
        assert "alert-001" in str(payload)
        assert "alert-002" in str(payload)
