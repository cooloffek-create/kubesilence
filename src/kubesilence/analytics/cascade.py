"""Cascade Detection — burst detection and root-cause suspect isolation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

CASCADE_WINDOW_SEC = 300  # 5 minutes for burst detection


def detect_cascades(
    alerts: list[dict[str, Any]],
    window_sec: int = CASCADE_WINDOW_SEC,
) -> list[dict[str, Any]]:
    """Identify alert cascades (storms) and label root-cause suspects.

    A cascade is a burst of ≥2 alerts across different *services*
    (from ``metadata.service`` or ``tags.service``) inside a tight
    rolling window.

    The alert with the earliest timestamp in each cascade is tagged
    as the *root_cause_suspect*.

    Parameters
    ----------
    alerts
        List of alert dicts with ``createdAt``, ``message``, and
        ``tags`` / ``metadata`` keys.
    window_sec
        Burst detection window in seconds.

    Returns
    -------
    list[dict]
        Each dict represents a cascade with keys:
        - ``start_time``, ``end_time``
        - ``alerts`` (the member alert indices)
        - ``services`` (unique services involved)
        - ``root_cause_suspect`` (index into *alerts*)
    """
    if not alerts:
        return []

    df = pd.DataFrame(alerts)
    df["ts"] = pd.to_datetime(df["createdAt"])
    df["service"] = df.apply(
        lambda r: (
            (r.get("tags") or {}).get("service")
            or (r.get("metadata") or {}).get("service", "unknown")
        ),
        axis=1,
    )
    df = df.sort_values("ts").reset_index(drop=True)

    cascades: list[dict[str, Any]] = []
    i = 0
    while i < len(df):
        window_end = df.loc[i, "ts"] + timedelta(seconds=window_sec)
        members = [i]
        services: set[str] = {df.loc[i, "service"]}
        for j in range(i + 1, len(df)):
            if df.loc[j, "ts"] > window_end:
                break
            members.append(j)
            services.add(df.loc[j, "service"])

        if len(services) >= 2 and len(members) >= 2:
            root_cause_idx = min(members, key=lambda idx: df.loc[idx, "ts"])
            cascades.append(
                {
                    "start_time": df.loc[members[0], "ts"].isoformat(),
                    "end_time": df.loc[members[-1], "ts"].isoformat(),
                    "alerts": members,
                    "services": sorted(services),
                    "root_cause_suspect": int(root_cause_idx),
                }
            )
            i = members[-1] + 1
        else:
            i += 1

    return cascades
