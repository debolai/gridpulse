{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['ba_code', 'fuel_code', 'period_utc'],
        on_schema_change='append_new_columns',
        **iceberg_table_config(partition_by=['month(period_utc)'])
    )
}}

-- Latest observed generation per (BA, fuel, hour); same watermark pattern as
-- int_grid__latest_values, so revisions and backfills both land.

with observations as (

    select * from {{ ref('stg_eia__fuel_type_data') }}
    {% if is_incremental() %}
    where ingested_at_utc > {{ incremental_watermark('ingested_at_utc') }}
    {% endif %}

),

ranked as (

    select
        *,
        row_number() over (
            partition by ba_code, fuel_code, period_utc
            order by ingested_at_utc desc, record_hash
        ) as recency_rank
    from observations

)

select
    ba_code,
    fuel_code,
    cast(period_utc as {{ timestamp_type() }}) as period_utc,
    generation_mwh,
    record_hash,
    run_id,
    cast(ingested_at_utc as {{ timestamp_type() }}) as ingested_at_utc
from ranked
where recency_rank = 1
