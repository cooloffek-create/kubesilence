"""DatadogProvider — Datadog Monitors API integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncGenerator

from kubesilence.providers.base import AlertRecord, BaseAlertProvider


class DatadogProvider(BaseAlertProvider):
    """Fetch alert events from the Datadog Events API.

    Scaffold — full implementation follows the same pagination,
    time-chunking, and retry patterns as OpsgenieProvider.
    """

    def __init__(self, api_key: str, app_key: str) -> None:
        self._api_key = api_key
        self._app_key = app_key

    async def get_alerts(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> AsyncGenerator[AlertRecord, None]:
        # Placeholder
        return
        yield  # make the generator valid  # noqa: B901

    async def create_silence(self, alert_ids: list[str], reason: str) -> dict[str, Any]:
        return {"status": "simulated", "silenced_ids": alert_ids}
