{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['ba_code', 'neighbor_ba_code', 'period_utc'],
        on_schema_change='append_new_columns',
        **iceberg_table_config(partition_by=['month(period_utc)'])
    )
}}

-- Hourly directional flow between a balancing authority and each directly connected
-- neighbour. Grain: BA × neighbour × UTC hour, as reported by the BA. Positive = the BA
-- exports to the neighbour (the platform's sign convention); for one BA-hour the flows add up
-- to total interchange in fct_grid_hourly. Neighbours outside the U.S. (Canadian and Mexican
-- operators such as HQT, IESO, CEN) are kept and flagged.

with latest as (

    select * from {{ ref('int_interchange__latest_values') }}
    {% if is_incremental() %}
    where ingested_at_utc > {{ incremental_watermark('last_ingested_at_utc') }}
    {% endif %}

),

localized as (

    select
        latest.*,
        neighbor.ba_code is null as is_international_neighbor,
        ba.time_zone,
        {{ utc_to_local('latest.period_utc', 'ba.time_zone') }} as period_local
    from latest
    left join {{ ref('dim_balancing_authority') }} as ba
        on latest.from_ba_code = ba.ba_code
    left join {{ ref('dim_balancing_authority') }} as neighbor
        on latest.to_ba_code = neighbor.ba_code

)

select
    cast(from_ba_code as varchar) as ba_code,
    cast(to_ba_code as varchar) as neighbor_ba_code,
    cast(to_ba_name as varchar) as neighbor_ba_name,
    cast(is_international_neighbor as boolean) as is_international_neighbor,
    cast(period_utc as {{ timestamp_type() }}) as period_utc,
    period_local,
    cast(period_local as date) as date_local,
    cast(hour(period_local) as integer) as hour_local,
    interchange_mwh,
    cast(ingested_at_utc as {{ timestamp_type() }}) as last_ingested_at_utc
from localized
