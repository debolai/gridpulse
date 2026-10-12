-- MetricFlow's daily time spine: one row per day from the start of EIA-930 fuel data
-- (2018-07-01) to 2030. sequence() is capped at 10,000 elements, which days fit within.

select cast(day_value as date) as date_day
from unnest(sequence(date '2018-07-01', date '2030-12-31', interval '1' day)) as days (day_value)
