{{ config(**iceberg_table_config(partition_by=['month(period_utc)'])) }}

-- Population-weighted temperature per balancing authority and UTC hour, from the stations in
-- seed ba_weather_stations. A station without a value for the hour is left out and the
-- weights of the others are rescaled; weight_coverage says how much of the BA's population
-- weight was available (1.0 = every station).

with stations as (

    select
        ba_code,
        station_id,
        cast(metro_population as double)
        / sum(cast(metro_population as double)) over (partition by ba_code) as weight
    from {{ ref('ba_weather_stations') }}

),

joined as (

    select
        stations.ba_code,
        hourly.period_utc,
        stations.weight,
        hourly.temperature_c,
        hourly.is_interpolated,
        hourly.last_ingested_at_utc
    from stations
    inner join {{ ref('int_weather__station_hourly') }} as hourly
        on stations.station_id = hourly.station_id
    where hourly.temperature_c is not null

)

select
    ba_code,
    period_utc,
    sum(weight * temperature_c) / sum(weight) as temperature_c,
    sum(weight) as weight_coverage,
    cast(count(*) as integer) as stations_reporting,
    cast(sum(case when is_interpolated then 1 else 0 end) as integer) as stations_interpolated,
    cast(max(last_ingested_at_utc) as {{ timestamp_type() }}) as last_ingested_at_utc
from joined
group by ba_code, period_utc
