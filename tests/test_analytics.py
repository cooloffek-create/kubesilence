"""Tests for analytics engine (deduplication + cascade detection)."""

from kubesilence.analytics.cascade import detect_cascades
from kubesilence.analytics.deduplication import cluster_duplicates

SAMPLE_ALERTS = [
    {
        "id": "1",
        "createdAt": "2025-01-01T00:00:00Z",
        "message": "CPU usage > 90% on server-a",
        "tags": {"service": "compute", "env": "prod"},
    },
    {
        "id": "2",
        "createdAt": "2025-01-01T00:00:30Z",
        "message": "CPU usage > 90% on server-a",
        "tags": {"service": "compute", "env": "prod"},
    },
    {
        "id": "3",
        "createdAt": "2025-01-01T00:01:00Z",
        "message": "Disk space low on server-b",
        "tags": {"service": "storage", "env": "prod"},
    },
    {
        "id": "4",
        "createdAt": "2025-01-01T00:01:05Z",
        "message": "CPU usage > 90% on server-a",
        "tags": {"service": "compute", "env": "prod"},
    },
    {
        "id": "5",
        "createdAt": "2025-01-01T00:05:00Z",
        "message": "Memory leak detected in api-gateway",
        "tags": {"service": "gateway", "env": "prod"},
    },
]


class TestDeduplication:
    def test_empty_list(self):
        assert cluster_duplicates([]) == []

    def test_no_duplicates(self):
        result = cluster_duplicates(SAMPLE_ALERTS[:1])
        assert result == []

    def test_identical_messages_in_window(self):
        clusters = cluster_duplicates(SAMPLE_ALERTS[:3], time_window_sec=60)
        assert len(clusters) >= 1
        # alerts 0 and 1 are identical messages 30s apart
        assert clusters[0] == [0, 1]

    def test_out_of_window_not_clustered(self):
        """Alerts 45+ seconds apart with a 10s window produce no cluster."""
        clusters = cluster_duplicates(SAMPLE_ALERTS, time_window_sec=10)
        # No two identical messages fall inside the same 10s bucket
        # (alert 0 vs 1 are 30s apart), so no clusters expected
        assert len(clusters) == 0


class TestCascadeDetection:
    def test_empty_list(self):
        assert detect_cascades([]) == []

    def test_single_alert_no_cascade(self):
        result = detect_cascades([SAMPLE_ALERTS[0]])
        assert result == []

    def test_multi_service_burst_detected(self):
        """CPU alert (compute) + Disk alert (storage) inside 120s -> cascade."""
        cascades = detect_cascades(SAMPLE_ALERTS[:3], window_sec=120)
        assert len(cascades) >= 1
        assert len(cascades[0]["services"]) >= 2
