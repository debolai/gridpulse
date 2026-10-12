"""EIA routes the platform extracts. Fuel-type and interchange join in phase B1."""

from dataclasses import dataclass

from gridpulse_ingestion.eia.models import EIARow, RegionDataRow


@dataclass(frozen=True)
class Route:
    name: str
    path: str
    model: type[EIARow]
    # A total order over rows. Paging without one can skip or repeat rows between pages.
    sort_columns: tuple[str, ...]
    facet: str
    # Business columns, in table order, after `period`. Values are strings in the raw table.
    columns: tuple[str, ...]
    # Fields whose values identify a version of a row (hashed into `_record_hash`).
    hash_fields: tuple[str, ...]


REGION_DATA = Route(
    name="region-data",
    path="electricity/rto/region-data/data/",
    model=RegionDataRow,
    sort_columns=("period", "respondent", "type"),
    facet="respondent",
    columns=("respondent", "respondent_name", "type", "type_name", "value", "value_units"),
    hash_fields=("period", "respondent", "type", "value", "value_units"),
)

ROUTES: dict[str, Route] = {r.name: r for r in (REGION_DATA,)}
