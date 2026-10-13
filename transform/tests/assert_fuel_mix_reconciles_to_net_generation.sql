-- Generation by fuel (fuel-type-data) must add up to net generation (region-data, NG) for
-- each BA-hour, within var('reconciliation_tolerance') of NG or 1 MWh. A few hours legitimately
-- miss (partial fuel reports), so the test fails per BA only when the share of reconciled hours
-- drops below var('reconciliation_min_pass_rate'). BAs listed for this check in seed
-- `reconciliation_exceptions` (with the measured reason) are skipped. Returns one row per failing BA.

with fuel as (

    select ba_code, period_utc, sum(generation_mwh) as fuel_total_mwh
    from {{ ref('fct_generation_by_fuel_hourly') }}
    group by ba_code, period_utc

),

compared as (

    select
        grid.ba_code,
        case
            when abs(fuel.fuel_total_mwh - grid.net_generation_mwh)
                <= greatest({{ var('reconciliation_tolerance') }} * abs(grid.net_generation_mwh), 1)
                then 1
            else 0
        end as is_reconciled
    from {{ ref('fct_grid_hourly') }} as grid
    inner join fuel
        on grid.ba_code = fuel.ba_code
        and grid.period_utc = fuel.period_utc
    where grid.net_generation_mwh is not null
        and fuel.fuel_total_mwh is not null
        and grid.ba_code not in (
            select ba_code from {{ ref('reconciliation_exceptions') }}
            where check_name = 'fuel_mix_to_net_generation'
        )

)

select
    ba_code,
    count(*) as hours_compared,
    avg(cast(is_reconciled as double)) as reconciled_share
from compared
group by ba_code
having avg(cast(is_reconciled as double)) < {{ var('reconciliation_min_pass_rate') }}
