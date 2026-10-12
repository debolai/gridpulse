"""Row models for EIA API v2 routes.

Validation rules: required fields must be present (a missing field fails the batch), series
codes must be known, and values must be numeric strings or null. Unknown new fields are
allowed and kept in `_extra` so additive API changes never stop the pipeline.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EIA_HOURLY_FORMAT = "%Y-%m-%dT%H"


def parse_eia_hour(value: str) -> datetime:
    return datetime.strptime(value, EIA_HOURLY_FORMAT).replace(tzinfo=UTC)


class EIARow(BaseModel):
    """Fields shared by every EIA hourly route."""

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)

    period: str
    value: str | None
    value_units: str = Field(alias="value-units")

    @field_validator("period")
    @classmethod
    def _period_is_utc_hour(cls, v: str) -> str:
        parse_eia_hour(v)
        return v

    @field_validator("value")
    @classmethod
    def _value_is_numeric(cls, v: str | None) -> str | None:
        # EIA returns values as strings since API v2.1.6. Keep the string; staging casts it.
        if v is not None:
            float(v)
        return v

    @property
    def period_utc(self) -> datetime:
        return parse_eia_hour(self.period)

    @property
    def extra_fields(self) -> dict:
        return dict(self.model_extra or {})


class RegionDataRow(EIARow):
    """`electricity/rto/region-data`: demand, day-ahead forecast, net generation, interchange."""

    respondent: str
    respondent_name: str = Field(alias="respondent-name")
    type: Literal["D", "DF", "NG", "TI"]
    type_name: str = Field(alias="type-name")
