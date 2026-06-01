"""Alert Parser — normalize provider-specific schemas into a unified DataFrame.

Each monitoring provider (Opsgenie, Datadog, CloudWatch, …) returns alerts
with different field names and shapes.  This module bridges that gap by
providing a standardised schema that the analytics engine can rely on.

Usage
-----
    from kubesilence.analytics.parser import parse_alerts

    raw = await provider.get_alerts(start, end)
    # Collect into a list (the gen yields AlertRecord dicts)
    alerts = [a async for a in raw]
    df = parse_alerts(alerts, provider="opsgenie")
    # df now has standardised columns: id, created_at, message, …
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import pandas as pd

# ---------------------------------------------------------------------------
# Standardised schema  — every normalised DataFrame has exactly these columns
# ---------------------------------------------------------------------------
STANDARD_FIELDS: list[str] = [
    "id",  # unique alert identifier
    "created_at",  # parsed datetime (naive UTC)
    "message",  # alert title / summary
    "description",  # longer human-readable description
    "source",  # monitoring system name (e.g. "CloudWatch")
    "priority",  # severity level: P1–P5 or None
    "tags",  # dict of key/value labels
    "metadata",  # provider-specific extra payload
    "provider",  # which provider produced this alert ("mock", "opsgenie", …)
]

# Type alias so we can annotate the supported provider names
ProviderName = Literal["mock", "opsgenie", "datadog"]

# ---------------------------------------------------------------------------
# Provider field maps
# ---------------------------------------------------------------------------
# Each map tells the parser which source field to read for each standard
# column.  A value of ``None`` means the field is injected by the parser
# itself (e.g. ``provider`` is always set from the provider argument).
# ---------------------------------------------------------------------------
_PROVIDER_FIELD_MAP: dict[str, dict[str, str | None]] = {
    "mock": {
        "id": "id",
        "created_at": "createdAt",
        "message": "message",
        "description": "description",
        "source": "source",
        "priority": "priority",
        "tags": "tags",
        "metadata": "metadata",
        "provider": None,
    },
    "opsgenie": {
        # Opsgenie's GET /v2/alerts returns fields under "data" with these keys:
        #   id, createdAt, message, description, source, priority, tags, …
        # The shapes overlap with our flat schema almost one-to-one.
        "id": "id",
        "created_at": "createdAt",
        "message": "message",
        "description": "description",
        "source": "source",
        "priority": "priority",
        "tags": "tags",
        "metadata": "metadata",
        "provider": None,
    },
    "datadog": {
        # Datadog's Events API uses a different naming convention:
        #   id, date_happened, title, text, source_type_name, …
        "id": "id",
        "created_at": "date_happened",
        "message": "title",
        "description": "text",
        "source": "source_type_name",
        "priority": "priority",
        "tags": "tags",
        "metadata": None,  # collect remaining unknown fields here
        "provider": None,
    },
}


def parse_alerts(
    alerts: list[dict[str, Any]],
    provider: ProviderName = "mock",
) -> pd.DataFrame:
    """Normalise raw alert dicts from any provider into a unified DataFrame.

    Parameters
    ----------
    alerts
        Raw alert records as returned by a provider's ``get_alerts()``.
        Each element should be a flat dict (``AlertRecord`` or plain dict).
    provider
        Provider name.  Controls the field mapping used.
        Supported: ``"mock"``, ``"opsgenie"``, ``"datadog"``.

    Returns
    -------
    pd.DataFrame
        DataFrame with the standardised columns defined in
        ``STANDARD_FIELDS``.  ``created_at`` is parsed to
        ``datetime[UTC]``.  Missing source fields produce ``None``
        (never a ``KeyError``).

    Examples
    --------
    >>> import pandas as pd
    >>> raw = [{"id": "a1", "createdAt": "2025-06-01T10:00:00Z",
    ...         "message": "CPU high", "source": "CloudWatch",
    ...         "tags": {"env": "prod"}}]
    >>> df = parse_alerts(raw, provider="mock")
    >>> list(df.columns)
    ['id', 'created_at', 'message', 'description', 'source', 'priority', 'tags', 'metadata', 'provider']
    >>> df.iloc[0]["provider"]
    'mock'
    """
    field_map = _PROVIDER_FIELD_MAP.get(provider)
    if field_map is None:
        msg = f"Unknown provider {provider!r}.  Supported: {list(_PROVIDER_FIELD_MAP)}"
        raise ValueError(msg)

    rows: list[dict[str, Any]] = []
    for raw_alert in alerts:
        row: dict[str, Any] = {}
        for std_field, source_key in field_map.items():
            if source_key is None:
                row[std_field] = {
                    "provider": provider,
                    "metadata": _collect_metadata(raw_alert, field_map),
                }.get(std_field, None)
            else:
                row[std_field] = raw_alert.get(source_key)
        rows.append(row)

    # --- inject provider string (not nested) ---
    # The comprehension above sets provider from a temporary sentinel; override.
    for row in rows:
        row["provider"] = provider

    df = pd.DataFrame(rows, columns=STANDARD_FIELDS)

    # --- type coercion ---
    # Parse created_at from ISO-8601 string → datetime
    if "created_at" in df.columns:
        df["created_at"] = _parse_timestamps(df["created_at"])

    # Ensure tags is always a dict (or None)
    df["tags"] = df["tags"].apply(_ensure_dict)

    return df


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _parse_timestamps(series: pd.Series) -> pd.Series:
    """Parse ISO-8601 timestamp strings to datetime (naive UTC).

    - Handles ``Z`` suffix (converts to ``+00:00``).
    - Coerces numeric unix timestamps (``pd.to_datetime(unit='s')``).
    - Coerces values that are already ``datetime`` objects.
    - Invalid / missing values become ``pd.NaT`` (never crashes).
    """

    def _coerce_scalar(v: object) -> object:
        if isinstance(v, str):
            return v.replace("Z", "+00:00")
        # Numeric unix timestamps (Datadog) → parse as seconds-since-epoch
        if isinstance(v, (int, float)):
            return pd.to_datetime(v, unit="s", utc=True)
        return v

    cleaned = series.apply(_coerce_scalar)
    parsed = pd.to_datetime(cleaned, utc=True, errors="coerce")

    def _strip_tz(val: object) -> object:
        """Remove timezone info from a scalar datetime."""
        if pd.isna(val):
            return val
        if isinstance(val, datetime) and val.tzinfo is not None:
            return val.replace(tzinfo=None)
        return val

    return parsed.apply(_strip_tz)


def _ensure_dict(val: Any) -> dict[str, Any] | list | None:
    """Return *val* if it's a dict or list, otherwise ``None``.

    Most providers use dict-form tags (``{"key": "val"}``).  Datadog
    returns tags as a list of strings (``["key:val"]``).  Both are
    valid and preserved as-is.
    """
    return val if isinstance(val, (dict, list)) else None


def _collect_metadata(
    raw: dict[str, Any],
    field_map: dict[str, str | None],
) -> dict[str, Any]:
    """Gather source fields that aren't part of the standard schema.

    For providers where ``metadata`` is injected (``None`` in the map),
    this collects every source key that isn't already mapped, so no
    raw data is silently dropped.
    """
    mapped_keys = {v for v in field_map.values() if v is not None}
    return {k: v for k, v in raw.items() if k not in mapped_keys}
