"""Deterministic checks on a planned metric request. Prompts are suggestions; this is the
guarantee. Every message is written for the planner to read and fix on its next attempt."""

from gridpulse_agent.contract import MetricRequest

GRAINS = ("hour", "day", "week", "month", "quarter", "year")
PER_BA_METRICS = {"peak_demand"}  # max of single BA-hours: meaningless when BAs are pooled


def _base(name: str) -> str:
    """Strip a time grain: 'metric_time__day' -> 'metric_time'.

    'grid_hour__date_local__month' -> 'grid_hour__date_local'.
    """
    head, _, tail = name.rpartition("__")
    return head if head and tail in GRAINS else name


def validate(
    request: MetricRequest,
    catalog: list[dict],
    *,
    max_window_days: int,
    max_rows: int,
) -> list[str]:
    errors: list[str] = []
    by_name = {m["name"]: m for m in catalog}

    unknown = [m for m in request.metrics if m not in by_name]
    if unknown:
        errors.append(f"Unknown metric(s) {unknown}. Use only: {sorted(by_name)}.")
    known = [by_name[m] for m in request.metrics if m in by_name]

    if known:
        shared = set.intersection(*({_base(d) for d in m["dimensions"]} for m in known))
        entities = {d.split("__")[0] for d in shared if "__" in d}
        allowed = shared | entities | {"metric_time"}
        names = list(request.group_by) + [f.dimension for f in request.filters]
        bad = [n for n in names if _base(n) not in allowed]
        if bad:
            errors.append(
                f"Dimension(s) {bad} are not available for {request.metrics}. "
                f"Available: {sorted(allowed)} (time dimensions take a grain suffix, "
                f"e.g. metric_time__day)."
            )

    pooled = {"balancing_authority"} - {_base(g) for g in request.group_by}
    single_ba = any(f.dimension == "balancing_authority" and f.op == "=" for f in request.filters)
    for metric in PER_BA_METRICS & set(request.metrics):
        if pooled and not single_ba:
            errors.append(
                f"{metric} is the highest single BA-hour; across several BAs it is not a "
                f"combined peak. Group by balancing_authority or filter to one BA."
            )

    if request.end <= request.start:
        errors.append("end must be after start (end is exclusive).")
    elif (request.end - request.start).days > max_window_days:
        errors.append(f"Time window is longer than {max_window_days} days; narrow it.")

    if request.limit > max_rows:
        errors.append(f"limit must be at most {max_rows}.")
    return errors
