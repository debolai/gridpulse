-- MetricFlow's hourly time spine, UTC. Built as days x 24 hours because sequence() is capped
-- at 10,000 elements (an hourly sequence over 12 years would exceed it).

with day_values as (

    select spine_days.day_value
    from unnest(
        sequence(date '2018-07-01', date '2030-12-31', interval '1' day)
    ) as spine_days (day_value)

),

hour_values as (

    select spine_hours.hour_value
    from unnest(sequence(0, 23)) as spine_hours (hour_value)

)

select
    cast(
        date_add('hour', hour_values.hour_value, cast(day_values.day_value as timestamp))
        as {{ timestamp_type() }}
    ) as date_hour
from day_values
cross join hour_values