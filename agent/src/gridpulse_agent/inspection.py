"""Inspect: deterministic checks on a result before the answer goes out (blueprint step 6).

Code, not the model, works out the caveats: how complete the data behind the answer is, the
latest hour loaded, whether the window runs past it, and whether it includes recent hours EIA
may still revise. They are appended to the answer like the quality notes, after the number check.
"""

import math
from datetime import datetime, timedelta

from gridpulse_agent.contract import Filter, MetricRequest

INTERCONNECTIONS = {"Eastern", "Western", "ERCOT"}


def _scope_filters(f: Filter) -> list[Filter]:
    """demand_scope__scope_code -> the matching BA filter (scopes are groups of BAs)."""
    if f.op not in ("=", "in") or "US48" in f.values:
        return []  # the whole Lower 48, or an exclusion: check every BA
    inter = [v for v in f.values if v in INTERCONNECTIONS]
    regions = [v for v in f.values if v not in INTERCONNECTIONS]
    if inter and regions:
        return []  # filters are ANDed, so a mixed list can't be expressed: check every BA
    if inter:
        return [Filter(dimension="balancing_authority__interconnection", op="in", values=inter)]
    return [Filter(dimension="balancing_authority__region", op="in", values=regions)]


def coverage_request(request: MetricRequest) -> MetricRequest:
    """Valid and expected demand hours per BA, for the BAs and window the request covers.

    BA filters carry over, scope filters become BA filters, and other filters (fuel, quality)
    don't apply to coverage.
    """
    filters: list[Filter] = []
    for f in request.filters:
        if f.dimension == "balancing_authority" or f.dimension.startswith("balancing_authority__"):
            filters.append(f)
        elif f.dimension == "demand_scope__scope_code":
            filters += _scope_filters(f)
    return MetricRequest(
        metrics=["demand_hours_valid", "expected_hours"],
        group_by=["balancing_authority"],
        filters=filters,
        start=request.start,
        end=request.end,
        limit=1000,
    )


def has_data(result: dict, metrics: list[str]) -> bool:
    """False when no row has a value for any requested metric. A query with no group-by returns
    one row of nulls for an empty window, not zero rows."""
    cols = [i for i, name in enumerate(result["columns"]) if name in metrics]
    return any(row[i] is not None for row in result["rows"] for i in cols)


def _pct(fraction: float) -> str:
    """Rounded DOWN to one decimal, so 99.97% never reads as 100%."""
    value = math.floor(fraction * 1000) / 10
    return f"{value:g}%"


def caveats(
    request: MetricRequest,
    coverage_rows: list[list] | None,
    latest_hour: datetime | None,
    revision_window_days: int,
) -> list[str]:
    """Plain-language caveats. coverage_rows: [ba_code, valid_hours, expected_hours]."""
    out = []
    if coverage_rows is None:
        out.append("Couldn't check data completeness.")
    else:
        expected = sum(row[2] or 0 for row in coverage_rows)
        if expected:
            valid = sum(row[1] or 0 for row in coverage_rows)
            text = f"Data: {_pct(valid / expected)} of expected BA-hours have valid demand"
            rated = [(row[0], (row[1] or 0) / row[2]) for row in coverage_rows if row[2]]
            if len(rated) > 1:
                ba, share = min(rated, key=lambda r: r[1])
                if share < 0.98:
                    text += f" (lowest: {ba}, {_pct(share)})"
            out.append(text + ".")
        else:
            out.append("Data: no hours were expected from these BAs in this window.")
    if latest_hour is None:
        out.append("Couldn't check data freshness.")
    else:
        end = request.end.replace(tzinfo=None)
        latest = latest_hour.replace(tzinfo=None)
        text = f"Latest hour loaded: {latest:%Y-%m-%d %H:00} UTC"
        if end > latest + timedelta(hours=1):
            text += "; the window runs past it, so its last part has no data yet"
        out.append(text + ".")
        cutoff = latest - timedelta(days=revision_window_days)
        if end > cutoff:
            out.append(
                f"Hours after {cutoff:%Y-%m-%d} are recent; EIA may still revise them "
                f"(the pipeline re-reads the last {revision_window_days} days)."
            )
    return out
