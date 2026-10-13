{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['route', 'ba_code', 'item_code', 'period_utc', 'revised_at_utc'],
        on_schema_change='append_new_columns',
        **iceberg_table_config(partition_by=['month(period_utc)'])
    )
}}

-- Every change EIA made to a value after first publishing it, across the three routes.
-- Grain: route × BA × item × hour × revising load. item_code is the series (region-data), the
-- fuel (fuel-type-data) or the neighbour BA (interchange-data). A load that re-reads an
-- unchanged value is not a revision; A -> B -> A is two revisions.
-- Incremental runs take the keys that received a load since the last run, read ALL their
-- observations (a revision needs the previous version, however old), and keep the new events.

with observations as (

    select * from {{ ref('int_eia__observations') }}

),

{% if is_incremental() %}
touched as (

    select distinct
        route,
        ba_code,
        item_code,
        period_utc
    from observations
    where ingested_at_utc > {{ incremental_watermark('revised_at_utc') }}

),

scoped as (

    select observations.*
    from observations
    inner join touched
        on observations.route = touched.route
        and observations.ba_code = touched.ba_code
        and observations.item_code = touched.item_code
        and observations.period_utc = touched.period_utc

),
{% else %}
scoped as (

    select * from observations

),
{% endif %}

sequenced as (

    select
        *,
        lag(record_hash) over (
            partition by route, ba_code, item_code, period_utc order by ingested_at_utc
        ) as previous_hash,
        lag(value_mwh) over (
            partition by route, ba_code, item_code, period_utc order by ingested_at_utc
        ) as previous_value_mwh,
        lag(ingested_at_utc) over (
            partition by route, ba_code, item_code, period_utc order by ingested_at_utc
        ) as previous_ingested_at_utc
    from scoped

)

select
    route,
    ba_code,
    item_code,
    cast(period_utc as {{ timestamp_type() }}) as period_utc,
    previous_value_mwh,
    value_mwh as revised_value_mwh,
    cast(previous_ingested_at_utc as {{ timestamp_type() }}) as previous_ingested_at_utc,
    cast(ingested_at_utc as {{ timestamp_type() }}) as revised_at_utc
from sequenced
where
    previous_hash is not null
    and record_hash <> previous_hash
    {% if is_incremental() %}
    and ingested_at_utc > {{ incremental_watermark('revised_at_utc') }}
    {% endif %}
