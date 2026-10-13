-- Every observation of every EIA value across the three routes, in one shape.
-- Grain: route × BA × item × hour × load. item_code is the series (region-data), the fuel
-- (fuel-type-data) or the neighbour BA (interchange-data). Feeds the revision audit and the
-- re-check counts behind revision_rate.

select
    'region-data' as route,
    ba_code,
    series_code as item_code,
    period_utc,
    value_mwh,
    record_hash,
    ingested_at_utc
from {{ ref('stg_eia__region_data') }}

union all

select
    'fuel-type-data' as route,
    ba_code,
    fuel_code as item_code,
    period_utc,
    generation_mwh as value_mwh,
    record_hash,
    ingested_at_utc
from {{ ref('stg_eia__fuel_type_data') }}

union all

select
    'interchange-data' as route,
    from_ba_code as ba_code,
    to_ba_code as item_code,
    period_utc,
    interchange_mwh as value_mwh,
    record_hash,
    ingested_at_utc
from {{ ref('stg_eia__interchange_data') }}
