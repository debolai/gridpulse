{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['route', 'ba_code', 'item_code', 'period_utc'],
        on_schema_change='append_new_columns',
        **iceberg_table_config(partition_by=['month(period_utc)'])
    )
}}

-- How often each published EIA value was read, and whether it ever changed.
-- Grain: route × BA × item × UTC hour. The denominator for revision_rate: a value loaded only
-- once can't show a revision, so the rate is "revised / re-checked", where re-checked means
-- seen by at least two loads (the hourly 72 h window and the daily 30-day sweep re-read recent
-- hours; history loaded in one pass is published but never re-checked).
-- Revised means the value had more than one version (record hash), the same rule as
-- int_grid__revisions. Incremental runs recount the keys that received a load since the last
-- run, from all their observations.

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
    where ingested_at_utc > {{ incremental_watermark('last_ingested_at_utc') }}

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

counted as (

    select
        route,
        ba_code,
        item_code,
        period_utc,
        count(distinct ingested_at_utc) as loads,
        count(distinct record_hash) as versions,
        max(ingested_at_utc) as last_ingested_at_utc
    from scoped
    group by route, ba_code, item_code, period_utc

)

select
    cast(route as varchar) as route,
    cast(ba_code as varchar) as ba_code,
    cast(item_code as varchar) as item_code,
    cast(period_utc as {{ timestamp_type() }}) as period_utc,
    cast(loads as integer) as loads,
    cast(versions as integer) as versions,
    loads >= 2 as is_rechecked,
    loads >= 2 and versions >= 2 as is_revised,
    cast(last_ingested_at_utc as {{ timestamp_type() }}) as last_ingested_at_utc
from counted
