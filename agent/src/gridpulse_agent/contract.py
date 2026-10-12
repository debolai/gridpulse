"""The metric request the planner produces. Mirrors gridpulse_semantic.requests.MetricRequest
(a contract test keeps them in step); field descriptions double as instructions to the model."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Filter(BaseModel):
    dimension: str = Field(
        description="Exact dimension or entity name from the catalog, e.g. 'balancing_authority' "
        "(BA code) or 'balancing_authority__interconnection'."
    )
    op: Literal["=", "!=", "in", "not in"] = "="
    values: list[str] = Field(
        min_length=1,
        description="Values to match. BA codes (e.g. 'ERCO', 'PJM'), never full names.",
    )


class MetricRequest(BaseModel):
    metrics: list[str] = Field(
        min_length=1, max_length=6, description="Metric names from the catalog only."
    )
    group_by: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Dimensions to break the result down by, e.g. 'balancing_authority', "
        "'metric_time__day', 'metric_time__month', 'grid_hour__hour_local'. Empty for one total.",
    )
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    start: datetime = Field(description="Start of the window, inclusive, UTC (ISO 8601, ...Z).")
    end: datetime = Field(
        description="End of the window, EXCLUSIVE, UTC. 'September 2026' = start 2026-09-01, "
        "end 2026-10-01."
    )
    order_by: list[str] = Field(
        default_factory=list, max_length=4, description="e.g. '-peak_demand' for descending."
    )
    limit: int = Field(default=200, ge=1, le=1000)


class RouteDecision(BaseModel):
    route: Literal["metric", "definition", "out_of_scope"] = Field(
        description="metric: needs numbers from the data. definition: asks what a metric means "
        "or how it is calculated. out_of_scope: anything else (prices, trading, non-U.S. grids, "
        "general chat)."
    )
    reason: str = Field(description="One short sentence.")
