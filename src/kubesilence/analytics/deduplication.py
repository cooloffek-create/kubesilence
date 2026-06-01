"""Deduplication — fuzzy-matching and time-window clustering."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd
from rapidfuzz import fuzz

SIMILARITY_THRESHOLD = 85  # percent
DEFAULT_TIME_WINDOW_SEC = 60


def cluster_duplicates(
    alerts: list[dict[str, Any]],
    time_window_sec: int = DEFAULT_TIME_WINDOW_SEC,
    threshold: int = SIMILARITY_THRESHOLD,
) -> list[list[int]]:
    """Group similar alerts within a rolling time window.

    Two alerts are considered *potential duplicates* when:
    1. They fall inside the same rolling *time_window_sec* (by
       ``createdAt`` timestamp).
    2. Their ``message`` strings have a similarity **≥ threshold**
       (as measured by RapidFuzz's token sort ratio).

    Parameters
    ----------
    alerts
        List of alert dicts.  Each must have ``createdAt`` (ISO-8601
        string) and ``message`` keys.
    time_window_sec
        Rolling window width in seconds.
    threshold
        Similarity percentage threshold (0-100).

    Returns
    -------
    list[list[int]]
        A list of clusters, where each cluster is a list of alert
        indices into *alerts*.
    """
    if not alerts:
        return []

    df = pd.DataFrame(alerts)
    df["ts"] = pd.to_datetime(df["createdAt"])
    df = df.sort_values("ts").reset_index(drop=True)

    clusters: list[list[int]] = []
    assigned = [False] * len(df)

    for i in range(len(df)):
        if assigned[i]:
            continue
        cluster: list[int] = [i]
        window_end = df.loc[i, "ts"] + timedelta(seconds=time_window_sec)
        for j in range(i + 1, len(df)):
            if df.loc[j, "ts"] > window_end:
                break
            if assigned[j]:
                continue
            score = fuzz.token_sort_ratio(df.loc[i, "message"], df.loc[j, "message"])
            if score >= threshold:
                cluster.append(j)
                assigned[j] = True
        if len(cluster) > 1:
            clusters.append(cluster)
            assigned[i] = True

    return clusters
