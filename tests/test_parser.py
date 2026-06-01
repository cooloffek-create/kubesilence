"""Tests for the Alert Parser (provider schema normalisation)."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from kubesilence.analytics.parser import (
    STANDARD_FIELDS,
    parse_alerts,
)

# ---------------------------------------------------------------------------
# Fixtures — realistic provider payloads
# ---------------------------------------------------------------------------

MOCK_ALERTS = [
    {
        "id": "alert-001",
        "createdAt": "2025-06-01T10:00:00Z",
        "message": "CPU usage exceeded 90% on instance i-0abcd",
        "description": "High CPU utilization detected on prod instance",
        "source": "CloudWatch",
        "priority": "P2",
        "tags": {"service": "compute", "env": "prod"},
        "metadata": {"instance_id": "i-0abcd", "threshold": "90"},
    },
    {
        "id": "alert-002",
        "createdAt": "2025-06-01T10:00:30Z",
        "message": "Memory usage exceeded 90% on instance i-0abcd",
        "description": "High memory utilization detected",
        "source": "CloudWatch",
        "priority": "P3",
        "tags": {"service": "compute", "env": "prod"},
        "metadata": {"instance_id": "i-0abcd", "threshold": "90"},
    },
]

# Simulates what Opsgenie /v2/alerts returns
OPSGENIE_ALERTS = [
    {
        "id": "og-001",
        "createdAt": "2025-06-01T12:00:00Z",
        "message": "Opsgenie test alert",
        "description": "Just a test",
        "source": "Opsgenie",
        "priority": "P1",
        "tags": {"service": "monitoring", "team": "sre"},
        "metadata": {"integration": "api"},
    },
]

# Datadog Events API shape
DATADOG_ALERTS = [
    {
        "id": "dd-001",
        "date_happened": 1748750400,  # unix timestamp
        "title": "Datadog CPU Alert",
        "text": "CPU is too high on host xyz",
        "source_type_name": "Datadog",
        "priority": "normal",
        "tags": ["service:compute", "env:prod"],
        "host": "xyz.example.com",
        "device_name": "eth0",
    },
    {
        "id": "dd-002",
        "date_happened": 1748750460,
        "title": "Datadog Memory Alert",
        "text": "Memory usage at 95%",
        "source_type_name": "Datadog",
        "priority": "low",
        "tags": ["service:compute", "env:prod"],
        "host": "abc.example.com",
    },
]


# ===================================================================
# Basic shape
# ===================================================================


class TestParseAlertsShape:
    def test_returns_dataframe(self):
        df = parse_alerts(MOCK_ALERTS)
        assert isinstance(df, pd.DataFrame)

    def test_has_all_standard_columns(self):
        df = parse_alerts(MOCK_ALERTS)
        for col in STANDARD_FIELDS:
            assert col in df.columns, f"Missing column: {col}"
        assert list(df.columns) == STANDARD_FIELDS

    def test_correct_number_of_rows(self):
        df = parse_alerts(MOCK_ALERTS)
        assert len(df) == 2

    def test_provider_column_injected(self):
        df = parse_alerts(MOCK_ALERTS, provider="mock")
        assert (df["provider"] == "mock").all()
        df2 = parse_alerts(OPSGENIE_ALERTS, provider="opsgenie")
        assert (df2["provider"] == "opsgenie").all()


# ===================================================================
# Field mapping correctness
# ===================================================================


class TestFieldMapping:
    def test_mock_fields_mapped_correctly(self):
        df = parse_alerts(MOCK_ALERTS, provider="mock")
        assert df.iloc[0]["id"] == "alert-001"
        assert df.iloc[0]["message"] == "CPU usage exceeded 90% on instance i-0abcd"
        assert df.iloc[0]["description"] == "High CPU utilization detected on prod instance"
        assert df.iloc[0]["source"] == "CloudWatch"
        assert df.iloc[0]["priority"] == "P2"
        assert df.iloc[0]["tags"] == {"service": "compute", "env": "prod"}

    def test_opsgenie_fields_mapped_correctly(self):
        df = parse_alerts(OPSGENIE_ALERTS, provider="opsgenie")
        assert df.iloc[0]["id"] == "og-001"
        assert df.iloc[0]["message"] == "Opsgenie test alert"
        assert df.iloc[0]["priority"] == "P1"

    def test_datadog_fields_mapped_correctly(self):
        df = parse_alerts(DATADOG_ALERTS, provider="datadog")
        assert df.iloc[0]["id"] == "dd-001"
        assert df.iloc[0]["message"] == "Datadog CPU Alert"
        assert df.iloc[0]["description"] == "CPU is too high on host xyz"
        assert df.iloc[0]["source"] == "Datadog"
        assert df.iloc[0]["priority"] == "normal"


# ===================================================================
# Timestamp parsing
# ===================================================================


class TestTimestampParsing:
    def test_iso_z_parsed_to_datetime(self):
        df = parse_alerts(MOCK_ALERTS)
        ts = df.iloc[0]["created_at"]
        assert isinstance(ts, datetime)
        assert ts.year == 2025
        assert ts.month == 6
        assert ts.day == 1
        assert ts.hour == 10
        assert ts.minute == 0

    def test_datadog_unix_timestamp_parsed(self):
        df = parse_alerts(DATADOG_ALERTS, provider="datadog")
        ts = df.iloc[0]["created_at"]
        assert isinstance(ts, datetime)
        assert ts.year == 2025
        assert ts.month == 6
        assert ts.day == 1

    def test_missing_timestamp_becomes_nat(self):
        df = parse_alerts([{"id": "x", "message": "test"}], provider="mock")
        assert pd.isna(df.iloc[0]["created_at"])

    def test_already_datetime_preserved(self):
        """If a provider yields parsed datetime objects, keep them."""
        dt = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        alerts = [{"id": "x", "createdAt": dt, "message": "test", "tags": {}, "source": "test"}]
        df = parse_alerts(alerts)
        assert df.iloc[0]["created_at"] == dt.replace(tzinfo=None)


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    def test_empty_list(self):
        df = parse_alerts([])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == STANDARD_FIELDS

    def test_missing_source_fields_become_none(self):
        """If a provider field is absent, the standard column should be None."""
        alerts = [{"id": "only-id"}]  # no message, no createdAt, etc.
        df = parse_alerts(alerts, provider="mock")
        assert pd.isna(df.iloc[0].get("message")) or df.iloc[0]["message"] is None
        assert pd.isna(df.iloc[0].get("description")) or df.iloc[0]["description"] is None

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            parse_alerts([], provider="nonexistent")

    def test_tags_not_dict_becomes_none(self):
        df = parse_alerts(
            [
                {
                    "id": "x",
                    "createdAt": "2025-01-01T00:00:00Z",
                    "message": "test",
                    "tags": "not-a-dict",
                }
            ],
            provider="mock",
        )
        assert df.iloc[0]["tags"] is None

    def test_datadog_tags_list_preserved(self):
        """Datadog returns tags as a list of strings — that's fine, keep as-is."""
        df = parse_alerts(DATADOG_ALERTS, provider="datadog")
        assert df.iloc[0]["tags"] == ["service:compute", "env:prod"]

    def test_datadog_metadata_collects_extra_fields(self):
        """Fields not part of the standard mapping go into metadata."""
        df = parse_alerts(DATADOG_ALERTS, provider="datadog")
        meta = df.iloc[0]["metadata"]
        assert isinstance(meta, dict)
        assert "host" in meta
        assert meta["host"] == "xyz.example.com"
        assert "device_name" in meta


# ===================================================================
# Round-trip with analytics engine
# ===================================================================


class TestIntegrationWithAnalytics:
    """The parsed DataFrame must work with the existing analytics functions."""

    def test_deduplication_on_parsed_mock_data(self):
        from kubesilence.analytics.deduplication import cluster_duplicates

        df = parse_alerts(MOCK_ALERTS, provider="mock")
        dicts = df.to_dict(orient="records")
        for d in dicts:
            d["createdAt"] = d.pop("created_at")
        clusters = cluster_duplicates(dicts, time_window_sec=300)
        # Both alerts share many tokens (same instance, same 90% threshold)
        # so they may cluster depending on similarity threshold.
        # This test just verifies the round-trip works — no crashes.
        assert isinstance(clusters, list)

    def test_cascade_on_parsed_data(self):
        from kubesilence.analytics.cascade import detect_cascades

        df = parse_alerts(MOCK_ALERTS, provider="mock")
        dicts = df.to_dict(orient="records")
        for d in dicts:
            d["createdAt"] = d.pop("created_at")
        cascades = detect_cascades(dicts, window_sec=120)
        # Both MOCK_ALERTS have service "compute" — same service doesn't cascade
        for c in cascades:
            assert len(c["services"]) >= 2
