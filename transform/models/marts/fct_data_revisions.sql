{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['route', 'ba_code', 'item_code', 'period_utc', 'revised_at_utc'],
        on_schema_change='append_new_columns',
        **iceberg_table_config(partition_by=['month(period_utc)'])
    )
}}

-- Audit of EIA revisions: one row per change to a published value, with its size and how
-- late it came. Answers "how much does a BA revise its data, and how late?" and lets the
-- assistant warn that recent hours may still change.

with revisions as (

    select * from {{ ref('int_grid__revisions') }}
    {% if is_incremental() %}
    where revised_at_utc > {{ incremental_watermark('revised_at_utc') }}
    {% endif %}

)

select
    cast(route as varchar) as route,
    cast(ba_code as varchar) as ba_code,
    cast(item_code as varchar) as item_code,
    cast(period_utc as {{ timestamp_type() }}) as period_utc,
    cast(
        case
            when previous_value_mwh is null then 'filled'
            when revised_value_mwh is null then 'removed'
            else 'changed'
        end as varchar
    ) as revision_type,
    previous_value_mwh,
    revised_value_mwh,
    revised_value_mwh - previous_value_mwh as change_mwh,
    (revised_value_mwh - previous_value_mwh) / nullif(abs(previous_value_mwh), 0) as change_ratio,
    cast(previous_ingested_at_utc as {{ timestamp_type() }}) as previous_ingested_at_utc,
    cast(revised_at_utc as {{ timestamp_type() }}) as revised_at_utc,
    cast(date_diff('hour', period_utc, revised_at_utc) as integer) as hours_after_period
from revisions
