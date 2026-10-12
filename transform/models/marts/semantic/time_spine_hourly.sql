-- MetricFlow's hourly time spine, UTC. Built as days x 24 hours because sequence() is capped
-- at 10,000 elements (an hourly sequence over 12 years would exceed it).

with days as (

    select day_value
    from unnest(sequence(date '2018-07-01', date '2030-12-31', interval '1' day)) as days (day_value)

),

hours as (

    select hour_value
    from unnest(sequence(0, 23)) as hours (hour_value)

)

select
    cast(date_add('hour', hour_value, cast(day_value as timestamp)) as {{ timestamp_type() }}) as date_hour
from days
cross join hours
