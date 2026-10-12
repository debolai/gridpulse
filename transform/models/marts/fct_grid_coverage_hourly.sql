-- Every hour each balancing authority was expected to report, whether or not it did.
-- Grain: BA x UTC hour, from the BA's first reported hour to the latest hour with demand
-- anywhere (forecast rows run into the future, so they don't count) or the BA's retirement.
-- The denominator for data_completeness: a metric computed only from reported rows would
-- never see a missing hour.

with fct as (

    select * from {{ ref('fct_grid_hourly') }}

),

ba_bounds as (

    select
        fct.ba_code,
        min(fct.period_utc) as first_hour_utc,
        max(ba.retirement_date) as retirement_date
    from fct
    left join {{ ref('dim_balancing_authority') }} as ba
        on fct.ba_code = ba.ba_code
    group by fct.ba_code

),

latest as (

    select max(period_utc) as last_hour_utc
    from fct
    where demand_mwh is not null

),

expected as (

    select
        ba_bounds.ba_code,
        spine.date_hour as period_utc
    from ba_bounds
    cross join latest
    inner join {{ ref('time_spine_hourly') }} as spine
        on spine.date_hour >= ba_bounds.first_hour_utc
        and spine.date_hour <= latest.last_hour_utc
        and (
            ba_bounds.retirement_date is null
            or spine.date_hour < cast(ba_bounds.retirement_date as {{ timestamp_type() }})
        )

)

select
    cast(expected.ba_code as varchar) as ba_code,
    cast(expected.period_utc as {{ timestamp_type() }}) as period_utc,
    fct.demand_mwh is not null as is_demand_reported,
    fct.demand_forecast_mwh is not null as is_forecast_reported,
    fct.net_generation_mwh is not null as is_net_generation_reported,
    fct.total_interchange_mwh is not null as is_interchange_reported
from expected
left join fct
    on expected.ba_code = fct.ba_code
    and expected.period_utc = fct.period_utc
