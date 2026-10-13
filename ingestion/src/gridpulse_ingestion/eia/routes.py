"""EIA routes the platform extracts."""

from dataclasses import dataclass

from gridpulse_ingestion.eia.models import EIARow, FuelTypeRow, InterchangeRow, RegionDataRow


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

FUEL_TYPE_DATA = Route(
    name="fuel-type-data",
    path="electricity/rto/fuel-type-data/data/",
    model=FuelTypeRow,
    sort_columns=("period", "respondent", "fueltype"),
    facet="respondent",
    columns=("respondent", "respondent_name", "fueltype", "type_name", "value", "value_units"),
    hash_fields=("period", "respondent", "fueltype", "value", "value_units"),
)

# Faceted by the exporting side: `--respondents PJM` loads PJM's flows to all its neighbours.
INTERCHANGE_DATA = Route(
    name="interchange-data",
    path="electricity/rto/interchange-data/data/",
    model=InterchangeRow,
    sort_columns=("period", "fromba", "toba"),
    facet="fromba",
    columns=("fromba", "fromba_name", "toba", "toba_name", "value", "value_units"),
    hash_fields=("period", "fromba", "toba", "value", "value_units"),
)

ROUTES: dict[str, Route] = {r.name: r for r in (REGION_DATA, FUEL_TYPE_DATA, INTERCHANGE_DATA)}
