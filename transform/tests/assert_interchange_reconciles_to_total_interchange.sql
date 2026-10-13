-- A BA's flows to each neighbour (interchange-data) must add up to its total interchange
-- (region-data, TI) for each BA-hour, within var('reconciliation_tolerance') of TI or 1 MWh.
-- Fails per BA when the share of reconciled hours drops below var('reconciliation_min_pass_rate').
-- BAs listed for this check in seed `reconciliation_exceptions` (with the measured reason) are
-- skipped. Returns one row per failing BA.

with flows as (

    select ba_code, period_utc, sum(interchange_mwh) as flows_total_mwh
    from {{ ref('fct_interchange_hourly') }}
    group by ba_code, period_utc

),

compared as (

    select
        grid.ba_code,
        case
            when abs(flows.flows_total_mwh - grid.total_interchange_mwh)
                <= greatest(
                    {{ var('reconciliation_tolerance') }} * abs(grid.total_interchange_mwh), 1
                )
                then 1
            else 0
        end as is_reconciled
    from {{ ref('fct_grid_hourly') }} as grid
    inner join flows
        on grid.ba_code = flows.ba_code
        and grid.period_utc = flows.period_utc
    where grid.total_interchange_mwh is not null
        and flows.flows_total_mwh is not null
        and grid.ba_code not in (
            select ba_code from {{ ref('reconciliation_exceptions') }}
            where check_name = 'interchange_to_total_interchange'
        )

)

select
    ba_code,
    count(*) as hours_compared,
    avg(cast(is_reconciled as double)) as reconciled_share
from compared
group by ba_code
having avg(cast(is_reconciled as double)) < {{ var('reconciliation_min_pass_rate') }}
