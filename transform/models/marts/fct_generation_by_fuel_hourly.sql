{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['ba_code', 'fuel_code', 'period_utc'],
        on_schema_change='append_new_columns',
        **iceberg_table_config(partition_by=['month(period_utc)'])
    )
}}

-- Hourly net generation by fuel per balancing authority. Grain: BA × fuel × UTC hour.
-- Storage fuels (BAT, PS, ...) are negative while charging. Each row depends on one latest
-- value only, so incremental runs simply take the rows that changed since the last run.

with latest as (

    select * from {{ ref('int_generation__latest_values') }}
    {% if is_incremental() %}
    where ingested_at_utc > {{ incremental_watermark('last_ingested_at_utc') }}
    {% endif %}

),

localized as (

    select
        latest.*,
        ba.time_zone,
        {{ utc_to_local('latest.period_utc', 'ba.time_zone') }} as period_local
    from latest
    left join {{ ref('dim_balancing_authority') }} as ba
        on latest.ba_code = ba.ba_code

)

select
    cast(ba_code as varchar) as ba_code,
    cast(fuel_code as varchar) as fuel_code,
    cast(period_utc as {{ timestamp_type() }}) as period_utc,
    period_local,
    cast(period_local as date) as date_local,
    cast(hour(period_local) as integer) as hour_local,
    generation_mwh,
    cast(ingested_at_utc as {{ timestamp_type() }}) as last_ingested_at_utc
from localized
