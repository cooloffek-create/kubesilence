"""RemediationEngine — creates silence/mute rules via provider APIs.

Supports a **dry-run mode** that prints the API payload instead of
executing, acting as a safety layer before actual mutations.
"""

from __future__ import annotations

from typing import Any

from kubesilence.providers.base import BaseAlertProvider
from kubesilence.remediation.schema import SilenceRequest


class RemediationEngine:
    """Applies analytical findings by issuing silence rules.

    Parameters
    ----------
    provider
        The alert provider used to execute silence/mute commands.
    dry_run
        When ``True`` every silence request is logged but **never**
        sent to the provider API.  Safe for preview.
    """

    def __init__(
        self,
        provider: BaseAlertProvider,
        dry_run: bool = False,
    ) -> None:
        self._provider = provider
        self._dry_run = dry_run

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @dry_run.setter
    def dry_run(self, value: bool) -> None:
        self._dry_run = value

    async def silence_duplicates(
        self,
        cluster_indices: list[list[int]],
        alerts: list[dict[str, Any]],
        reason: str = "Auto-silenced — duplicate alert cluster",
        source: str = "dedup",
    ) -> list[dict[str, Any]]:
        """Silence all duplicate clusters found by the analytics engine.

        Parameters
        ----------
        cluster_indices
            Output from ``cluster_duplicates()`` / ``detect_cascades()``.
        alerts
            The original alert list (used to resolve indices → IDs).
        reason
            Human-readable reason attached to the silence rule.
        source
            Origin tag — ``"dedup"``, ``"cascade"``, or ``"manual"``.

        Returns
        -------
        list[dict]
            Provider responses (or dry-run payloads) for each silence.
        """
        provider_name = getattr(self._provider, "__class__", None)
        provider_tag = (
            provider_name.__name__.replace("Provider", "").lower() if provider_name else "generic"
        )

        results: list[dict[str, Any]] = []
        for cluster in cluster_indices:
            alert_ids = [alerts[i].get("id", str(i)) for i in cluster]

            request = SilenceRequest(
                alert_ids=alert_ids,
                reason=reason,
                source=source,
                dry_run=self._dry_run,
                cluster_metadata={
                    "cluster_size": len(cluster),
                    "indices": cluster,
                },
            )

            if self._dry_run:
                # Safety layer: return the constructed payload without
                # executing anything on the provider.
                results.append(
                    {
                        "dry_run": True,
                        "payload": request.to_provider_payload(provider_tag),
                        "summary": request.dry_run_summary(),
                    }
                )
            else:
                resp = await self._provider.create_silence(alert_ids, reason)
                results.append(resp)

        return results

    async def silence_request(
        self,
        request: SilenceRequest,
    ) -> dict[str, Any]:
        """Execute a single pre-built ``SilenceRequest``.

        Useful when callers want full control over the request shape
        (e.g. CLI accepts structured input from the user).
        """
        provider_name = getattr(self._provider, "__class__", None)
        provider_tag = (
            provider_name.__name__.replace("Provider", "").lower() if provider_name else "generic"
        )

        if request.dry_run or self._dry_run:
            return {
                "dry_run": True,
                "payload": request.to_provider_payload(provider_tag),
                "summary": request.dry_run_summary(),
            }

        return await self._provider.create_silence(request.alert_ids, request.reason)

    def build_payloads(
        self,
        cluster_indices: list[list[int]],
        alerts: list[dict[str, Any]],
        reason: str = "Auto-silenced — duplicate alert cluster",
        source: str = "dedup",
    ) -> list[dict[str, Any]]:
        """Construct payloads without executing anything.

        Purely local — no network calls.  Useful for previews,
        logging, and audit trails.
        """
        provider_name = getattr(self._provider, "__class__", None)
        provider_tag = (
            provider_name.__name__.replace("Provider", "").lower() if provider_name else "generic"
        )

        payloads: list[dict[str, Any]] = []
        for cluster in cluster_indices:
            alert_ids = [alerts[i].get("id", str(i)) for i in cluster]
            request = SilenceRequest(
                alert_ids=alert_ids,
                reason=reason,
                source=source,
                dry_run=True,
            )
            payloads.append(request.to_provider_payload(provider_tag))
        return payloads
