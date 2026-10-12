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
-- with local time derived from the BA's IANA zone (DST-aware). Incremental runs rebuild
-- only the BA-hours that received a new observation since the last run.

with

{% if is_incremental() %}
changed_hours as (

    select distinct ba_code, period_utc
    from {{ ref('int_grid__latest_values') }}
    where ingested_at_utc > {{ incremental_watermark('last_ingested_at_utc') }}

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

localized as (

    select
        pivoted.*,
        ba.time_zone,
        {{ utc_to_local('pivoted.period_utc', 'ba.time_zone') }} as period_local
    from pivoted
    left join {{ ref('dim_balancing_authority') }} as ba
        on pivoted.ba_code = ba.ba_code

)

select
    cast(ba_code as varchar) as ba_code,
    period_utc,
    period_local,
    cast(period_local as date) as date_local,
    cast(hour(period_local) as integer) as hour_local,
    cast(time_zone as varchar) as time_zone,
    demand_mwh,
    demand_forecast_mwh,
    net_generation_mwh,
    total_interchange_mwh,
    last_ingested_at_utc
from localized
