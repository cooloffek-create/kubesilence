"""BaseAlertProvider — abstract interface for all alert data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, AsyncGenerator


class AlertRecord(dict):
    """A single alert fetched from a provider API.

    Subclasses dict so it's JSON-serializable by default.  Concrete
    providers are free to add provider-specific fields.
    """


class BaseAlertProvider(ABC):
    """Interface every alert provider must implement.

    All data-ingestion edge cases (pagination, time-chunking,
    rate-limiting) are handled inside the concrete class.
    """

    @abstractmethod
    def get_alerts(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> AsyncGenerator[AlertRecord, None]:
        """Stream alerts within *start_date* … *end_date*.

        Yields
        ------
        AlertRecord
            One alert at a time.  The caller drives the generator so
            memory stays bounded even for millions of alerts.
        """
        ...

    @abstractmethod
    async def create_silence(self, alert_ids: list[str], reason: str) -> dict[str, Any]:
        """Create a mute / silence rule for the given alerts.

        Parameters
        ----------
        alert_ids
            Identifiers of the alerts to silence.
        reason
            Human-readable explanation (from the analytics engine).

        Returns
        -------
        dict
            Provider-specific response payload.
        """
        ...
