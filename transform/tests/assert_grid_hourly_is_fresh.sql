{#
  Freshness of the served data (blueprint: freshness enforced by checks and alerts): the latest
  hour with demand in fct_grid_hourly must be at most grid_max_lag_hours old. Demand, not
  max(period_utc): region-data carries day-ahead forecasts for future hours.
  Severity is `warn` by default so a dev build on an idle laptop lake still passes; the
  scheduled dbt_build DAG runs with --vars '{freshness_severity: error}' and alerts on failure.
  The cutoff is computed here in UTC (casting current_timestamp differs between Trino and Athena).
#}
{{ config(severity=var('freshness_severity', 'warn'), tags=['freshness']) }}
{% set cutoff = (modules.datetime.datetime.utcnow()
    - modules.datetime.timedelta(hours=var('grid_max_lag_hours'))).strftime('%Y-%m-%d %H:%M:%S') %}

select max(period_utc) as latest_demand_hour_utc
from {{ ref('fct_grid_hourly') }}
where demand_mwh is not null
having max(period_utc) is null or max(period_utc) < timestamp '{{ cutoff }}'
