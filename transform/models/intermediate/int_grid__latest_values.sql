{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['ba_code', 'series_code', 'period_utc'],
        on_schema_change='append_new_columns',
        **iceberg_table_config(partition_by=['month(period_utc)'])
    )
}}

-- The revision-resolving model: the latest observed value of each (BA, series, hour).
-- Incremental runs read only observations loaded since the last run (a watermark on
-- ingested_at_utc), whatever hours they cover, so backfills and late revisions both land.

with observations as (

    select * from {{ ref('stg_eia__region_data') }}
    {% if is_incremental() %}
    where ingested_at_utc > {{ incremental_watermark('ingested_at_utc') }}
    {% endif %}

),

ranked as (

    select
        *,
        row_number() over (
            partition by ba_code, series_code, period_utc
            order by ingested_at_utc desc, record_hash
        ) as recency_rank
    from observations

)

select
    ba_code,
    series_code,
    series_name,
    period_utc,
    value_mwh,
    record_hash,
    run_id,
    ingested_at_utc
from ranked
where recency_rank = 1
