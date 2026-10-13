{{ config(**iceberg_table_config(partition_by=['month(period_utc)'])) }}

-- Data-quality flags per (BA, series, hour). Bad values are flagged, never deleted.
--   missing:  the BA reported the hour but not this value (null)
--   zero:     exactly 0
--   negative: below 0
--   spike:    differs from BOTH adjacent hours by more than var('spike_threshold'), in the same
--             direction (a one-hour outlier, not a level shift)
-- quality_status applies per-series rules: demand cannot be zero or negative (invalid); a zero
-- forecast, zero or negative net generation, and spikes are suspect; total interchange changes
-- sign as flows reverse, so only "missing" applies to it.
-- A table, not incremental: a spike depends on the neighbouring hours, so a revision to one
-- hour can change the flag of the hour next to it.

with series as (

    select
        ba_code,
        series_code,
        period_utc,
        value_mwh,
        lag(value_mwh) over (
            partition by ba_code, series_code order by period_utc
        ) as previous_mwh,
        lag(period_utc) over (
            partition by ba_code, series_code order by period_utc
        ) as previous_period_utc,
        lead(value_mwh) over (
            partition by ba_code, series_code order by period_utc
        ) as next_mwh,
        lead(period_utc) over (
            partition by ba_code, series_code order by period_utc
        ) as next_period_utc
    from {{ ref('int_grid__latest_values') }}

),

flagged as (

    select
        ba_code,
        series_code,
        period_utc,
        value_mwh,
        value_mwh is null as is_missing,
        coalesce(value_mwh = 0, false) as is_zero,
        coalesce(value_mwh < 0, false) as is_negative,
        coalesce(
            series_code in ('D', 'DF', 'NG')
            -- neighbours must be the adjacent hours, not the next reported ones after a gap
            and previous_period_utc = period_utc - interval '1' hour
            and next_period_utc = period_utc + interval '1' hour
            and previous_mwh > 0
            and next_mwh > 0
            and (
                (
                    value_mwh > previous_mwh * (1 + {{ var('spike_threshold') }})
                    and value_mwh > next_mwh * (1 + {{ var('spike_threshold') }})
                )
                or (
                    value_mwh < previous_mwh * (1 - {{ var('spike_threshold') }})
                    and value_mwh < next_mwh * (1 - {{ var('spike_threshold') }})
                )
            ),
            false
        ) as is_spike
    from series

)

select
    ba_code,
    series_code,
    cast(period_utc as {{ timestamp_type() }}) as period_utc,
    value_mwh,
    is_missing,
    is_zero,
    is_negative,
    is_spike,
    case
        when is_missing then 'missing'
        when series_code = 'TI' then 'ok'
        when series_code = 'D' and (is_zero or is_negative) then 'invalid'
        when series_code = 'DF' and is_negative then 'invalid'
        when is_zero or is_negative or is_spike then 'suspect'
        else 'ok'
    end as quality_status
from flagged
