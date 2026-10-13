"""The metric-request contract shared by the API and the agent.

A request names governed metrics and dimensions; it never contains SQL. Filters are structured
and rendered here into MetricFlow's where-syntax with typed, escaped literals, so callers
(including an LLM) can't inject SQL or compare timestamps to strings.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

NAME = re.compile(r"^[a-z][a-z0-9_]*$")
GRAINS = ("hour", "day", "week", "month", "quarter", "year")
MAX_ROWS = 5000


class Filter(BaseModel):
    """`dimension op values`, e.g. balancing_authority__interconnection in [Eastern, ERCOT]."""

    dimension: str
    op: Literal["=", "!=", "in", "not in"] = "="
    values: list[str] = Field(min_length=1, max_length=100)

    @field_validator("dimension")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        if not NAME.match(v):
            raise ValueError(f"invalid dimension name {v!r}")
        return v

    @model_validator(mode="after")
    def _single_value_ops(self) -> "Filter":
        if self.op in ("=", "!=") and len(self.values) != 1:
            raise ValueError(f"op {self.op!r} takes exactly one value")
        if self.is_boolean:
            self.values = [v.lower() for v in self.values]
            if not set(self.values) <= {"true", "false"}:
                raise ValueError(f"{self.dimension} is true/false; got {self.values}")
        return self

    @property
    def is_boolean(self) -> bool:
        """Boolean dimensions are named is_* (project convention), e.g. fuel_type__is_renewable.
        Their values are rendered as TRUE/FALSE: a quoted 'true' fails on Trino and Athena."""
        return self.dimension.rsplit("__", 1)[-1].startswith("is_")


class MetricRequest(BaseModel):
    """What to compute. Time range is half-open [start, end) in UTC."""

    metrics: list[str] = Field(min_length=1, max_length=6)
    group_by: list[str] = Field(default_factory=list, max_length=4)
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    start: datetime | None = None
    end: datetime | None = None
    order_by: list[str] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=1000, ge=1, le=MAX_ROWS)

    @field_validator("metrics", "group_by")
    @classmethod
    def _safe_names(cls, names: list[str]) -> list[str]:
        for name in names:
            if not NAME.match(name):
                raise ValueError(f"invalid name {name!r}")
        return names

    @field_validator("order_by")
    @classmethod
    def _safe_order(cls, names: list[str]) -> list[str]:
        for name in names:
            if not NAME.match(name.removeprefix("-")):
                raise ValueError(f"invalid order_by {name!r}")
        return names

    @model_validator(mode="after")
    def _valid_window(self) -> "MetricRequest":
        for ts in (self.start, self.end):
            if ts is not None and ts.tzinfo is not None and ts.utcoffset().total_seconds() != 0:
                raise ValueError("start/end must be UTC")
        if self.start and self.end and self.end <= self.start:
            raise ValueError("end must be after start")
        return self


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _timestamp(ts: datetime) -> str:
    return f"TIMESTAMP '{ts.replace(tzinfo=None).isoformat(sep=' ', timespec='seconds')}'"


def render_where(request: MetricRequest, entity_names: set[str]) -> list[str]:
    """MetricFlow where-constraints for the request's filters and time window.

    The time window is a filter on metric_time at hour grain with typed TIMESTAMP literals.
    MetricFlow's own start/end parameters snap to the query grain (a day-grain query ending
    2026-09-02 23:00 became `<= '2026-09-02'`, i.e. only that day's first hour on hourly data).
    """
    where = []
    for f in request.filters:
        ref = (
            f"{{{{ Entity('{f.dimension}') }}}}"
            if f.dimension in entity_names
            else f"{{{{ Dimension('{f.dimension}') }}}}"
        )
        render = (lambda v: v.upper()) if f.is_boolean else _literal
        if f.op in ("=", "!="):
            where.append(f"{ref} {f.op} {render(f.values[0])}")
        else:
            where.append(f"{ref} {f.op.upper()} ({', '.join(render(v) for v in f.values)})")
    metric_hour = "{{ TimeDimension('metric_time', 'hour') }}"
    if request.start is not None:
        where.append(f"{metric_hour} >= {_timestamp(request.start)}")
    if request.end is not None:
        where.append(f"{metric_hour} < {_timestamp(request.end)}")
    return where
