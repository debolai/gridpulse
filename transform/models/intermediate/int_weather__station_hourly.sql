{{ config(**iceberg_table_config(partition_by=['month(period_utc)'])) }}

-- Hourly temperature per weather station. Grain: station × UTC hour, from the station's first
-- to last reported hour. The value for hour [H, H+1) is the mean of the QC-passed reports in
-- it; a gap of up to var('weather_max_gap_hours') hours is filled by linear interpolation
-- between the reports around it (and flagged); longer gaps stay null.
-- A table: an interpolated hour depends on reports that arrive later.

with readings as (

    select
        station_id,
        date_trunc('hour', observed_at_utc) as period_utc,
        avg(temperature_c) as temperature_c,
        max(ingested_at_utc) as ingested_at_utc
    from {{ ref('stg_noaa__observations') }}
    where temperature_passed_qc
    group by station_id, date_trunc('hour', observed_at_utc)

),

bounds as (

    select
        station_id,
        min(period_utc) as first_hour,
        max(period_utc) as last_hour
    from readings
    group by station_id

),

spine as (

    select
        bounds.station_id,
        cast(time_spine.date_hour as {{ timestamp_type() }}) as period_utc
    from bounds
    inner join {{ ref('time_spine_hourly') }} as time_spine
        on time_spine.date_hour >= bounds.first_hour
        and time_spine.date_hour <= bounds.last_hour

),

filled as (

    select
        spine.station_id,
        spine.period_utc,
        readings.temperature_c,
        readings.ingested_at_utc,
        last_value(readings.temperature_c) ignore nulls over (
            partition by spine.station_id order by spine.period_utc
            rows between unbounded preceding and 1 preceding
        ) as previous_c,
        last_value(case when readings.temperature_c is not null then spine.period_utc end)
            ignore nulls over (
                partition by spine.station_id order by spine.period_utc
                rows between unbounded preceding and 1 preceding
            ) as previous_hour,
        last_value(readings.ingested_at_utc) ignore nulls over (
            partition by spine.station_id order by spine.period_utc
            rows between unbounded preceding and 1 preceding
        ) as previous_ingested_at_utc,
        first_value(readings.temperature_c) ignore nulls over (
            partition by spine.station_id order by spine.period_utc
            rows between 1 following and unbounded following
        ) as next_c,
        first_value(case when readings.temperature_c is not null then spine.period_utc end)
            ignore nulls over (
                partition by spine.station_id order by spine.period_utc
                rows between 1 following and unbounded following
            ) as next_hour,
        first_value(readings.ingested_at_utc) ignore nulls over (
            partition by spine.station_id order by spine.period_utc
            rows between 1 following and unbounded following
        ) as next_ingested_at_utc
    from spine
    left join readings
        on spine.station_id = readings.station_id
        and spine.period_utc = readings.period_utc

),

interpolated as (

    select
        *,
        (
            temperature_c is null
            and previous_hour is not null
            and next_hour is not null
            and date_diff('hour', previous_hour, next_hour) - 1
            <= {{ var('weather_max_gap_hours') }}
        ) as is_interpolatable
    from filled

)

select
    station_id,
    period_utc,
    case
        when temperature_c is not null then temperature_c
        when is_interpolatable then
            previous_c + (next_c - previous_c)
            * date_diff('hour', previous_hour, period_utc)
            / cast(date_diff('hour', previous_hour, next_hour) as double)
    end as temperature_c,
    coalesce(is_interpolatable, false) as is_interpolated,
    cast(
        case
            when temperature_c is not null then ingested_at_utc
            when is_interpolatable
                then greatest(previous_ingested_at_utc, next_ingested_at_utc)
        end as {{ timestamp_type() }}
    ) as last_ingested_at_utc
from interpolated
