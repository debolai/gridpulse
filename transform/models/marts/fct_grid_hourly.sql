{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['ba_code', 'period_utc'],
        on_schema_change='append_new_columns',
        **iceberg_table_config(partition_by=['month(period_utc)'])
    )
}}

-- One row per balancing authority and UTC hour: the four region-data series side by side,
-- with local time derived from the BA's IANA zone (DST-aware) and a quality status per series
-- (int_grid__quality_flags; a series absent for the hour is "missing"). Incremental runs
-- rebuild the BA-hours that received a new observation since the last run, plus the hour on
-- each side, because a spike flag depends on the neighbouring hours.

with

{% if is_incremental() %}
changed as (

    select distinct ba_code, period_utc
    from {{ ref('int_grid__latest_values') }}
    where ingested_at_utc > {{ incremental_watermark('last_ingested_at_utc') }}

),

changed_hours as (

    select ba_code, period_utc from changed
    union
    select ba_code, period_utc - interval '1' hour from changed
    union
    select ba_code, period_utc + interval '1' hour from changed

),
{% endif %}

latest as (

    select latest.*
    from {{ ref('int_grid__latest_values') }} as latest
    {% if is_incremental() %}
    inner join changed_hours
        on latest.ba_code = changed_hours.ba_code
        and latest.period_utc = changed_hours.period_utc
    {% endif %}

),

pivoted as (

    select
        ba_code,
        period_utc,
        max(case when series_code = 'D' then value_mwh end) as demand_mwh,
        max(case when series_code = 'DF' then value_mwh end) as demand_forecast_mwh,
        max(case when series_code = 'NG' then value_mwh end) as net_generation_mwh,
        max(case when series_code = 'TI' then value_mwh end) as total_interchange_mwh,
        max(ingested_at_utc) as last_ingested_at_utc
    from latest
    group by ba_code, period_utc

),

statuses as (

    select
        flags.ba_code,
        flags.period_utc,
        max(case when flags.series_code = 'D' then flags.quality_status end) as demand_status,
        max(case when flags.series_code = 'DF' then flags.quality_status end) as forecast_status,
        max(case when flags.series_code = 'NG' then flags.quality_status end) as generation_status,
        max(case when flags.series_code = 'TI' then flags.quality_status end) as interchange_status
    from {{ ref('int_grid__quality_flags') }} as flags
    {% if is_incremental() %}
    inner join changed_hours
        on flags.ba_code = changed_hours.ba_code
        and flags.period_utc = changed_hours.period_utc
    {% endif %}
    group by flags.ba_code, flags.period_utc

),

localized as (

    select
        pivoted.*,
        statuses.demand_status,
        statuses.forecast_status,
        statuses.generation_status,
        statuses.interchange_status,
        ba.time_zone,
        {{ utc_to_local('pivoted.period_utc', 'ba.time_zone') }} as period_local
    from pivoted
    left join statuses
        on pivoted.ba_code = statuses.ba_code
        and pivoted.period_utc = statuses.period_utc
    left join {{ ref('dim_balancing_authority') }} as ba
        on pivoted.ba_code = ba.ba_code

)

select
    cast(ba_code as varchar) as ba_code,
    -- Explicit casts pin the engine's timestamp type (see timestamp_type()), including when
    -- dbt unit tests feed this model fixtures typed from the upstream Iceberg table.
    cast(period_utc as {{ timestamp_type() }}) as period_utc,
    period_local,
    cast(period_local as date) as date_local,
    cast(hour(period_local) as integer) as hour_local,
    cast(time_zone as varchar) as time_zone,
    demand_mwh,
    demand_forecast_mwh,
    net_generation_mwh,
    total_interchange_mwh,
    cast(coalesce(demand_status, 'missing') as varchar) as demand_quality_status,
    cast(coalesce(forecast_status, 'missing') as varchar) as demand_forecast_quality_status,
    cast(coalesce(generation_status, 'missing') as varchar) as net_generation_quality_status,
    cast(coalesce(interchange_status, 'missing') as varchar) as total_interchange_quality_status,
    cast(last_ingested_at_utc as {{ timestamp_type() }}) as last_ingested_at_utc
from localized
