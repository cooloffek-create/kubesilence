"""OpsgenieProvider — Opsgenie API integration with pagination & retry."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from kubesilence.providers.base import AlertRecord, BaseAlertProvider


class OpsgenieProvider(BaseAlertProvider):
    """Fetch alerts from the Opsgenie /v2/alerts endpoint.

    Handles
    - cursor-based pagination (streaming, no OOM)
    - time-chunking (splits long windows into day-sized slices)
    - rate-limit retry via tenacity (exponential back-off on 429)
    """

    MAX_CHUNK_DAYS = 1  # split query windows into day chunks
    PAGE_LIMIT = 100  # alerts per API page
    MAX_RETRIES = 5
    BASE_URL = "https://api.opsgenie.com/v2"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def get_alerts(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> AsyncGenerator[AlertRecord, None]:
        """Stream alerts, auto-chunking and paginating under the hood."""
        for chunk_start, chunk_end in self._chunk_window(start_date, end_date):
            cursor: str | None = None
            while True:
                payload = await self._fetch_page(chunk_start, chunk_end, cursor)
                for alert in payload.get("data", []):
                    yield AlertRecord(alert)
                cursor = payload.get("paging", {}).get("next")
                if not cursor:
                    break

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type(Exception),  # tightened per provider
    )
    async def _fetch_page(
        self,
        start: datetime,
        end: datetime,
        cursor: str | None,
    ) -> dict[str, Any]:
        """Single API call — tenacity handles 429 retries automatically."""
        # Placeholder: real HTTP call would go here
        await asyncio.sleep(0.01)
        return {"data": [], "paging": {}}

    async def create_silence(self, alert_ids: list[str], reason: str) -> dict[str, Any]:
        """POST a silence rule to Opsgenie."""
        # Placeholder
        await asyncio.sleep(0.01)
        return {"status": "simulated", "silenced_ids": alert_ids}

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    @staticmethod
    def _chunk_window(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        """Split date range into day-sized chunks.

        Many alert APIs (including Opsgenie) reject queries spanning
        more than a few days.  This method breaks a long window into
        non-overlapping day chunks.
        """
        result: list[tuple[datetime, datetime]] = []
        current = start
        while current < end:
            chunk_end = min(current + timedelta(days=OpsgenieProvider.MAX_CHUNK_DAYS), end)
            result.append((current, chunk_end))
            current = chunk_end
        return result
