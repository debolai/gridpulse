-- Hourly demand summed over standard groups of balancing authorities: each interconnection,
-- each EIA region, and the Lower 48. Grain: scope x UTC hour. The basis for
-- coincident_peak_demand (the highest combined hour), which MetricFlow can't compute from
-- BA-hours: it would need a sum per hour followed by a max over hours.
-- Every expected hour is kept. A BA that didn't report only lowers that hour's sum, so
-- bas_reported / bas_expected say how complete each hour is; flagged values are counted, not
-- dropped (the metric layer decides what to exclude).

with ba_hours as (

    select
        cov.period_utc,
        ba.interconnection,
        ba.region_code,
        grid.demand_mwh,
        cov.is_demand_reported,
        coalesce(grid.demand_quality_status, 'missing') not in ('ok', 'missing') as is_flagged
    from {{ ref('fct_grid_coverage_hourly') }} as cov
    inner join {{ ref('dim_balancing_authority') }} as ba
        on cov.ba_code = ba.ba_code
    left join {{ ref('fct_grid_hourly') }} as grid
        on cov.ba_code = grid.ba_code
        and cov.period_utc = grid.period_utc
    -- Generation-only BAs never report demand; counting them would make no hour complete.
    where not coalesce(ba.is_generation_only, false)

),

scoped as (

    select 'interconnection' as scope_type, interconnection as scope_code, ba_hours.*
    from ba_hours
    union all
    select 'region' as scope_type, region_code as scope_code, ba_hours.*
    from ba_hours
    union all
    select 'lower_48' as scope_type, 'US48' as scope_code, ba_hours.*
    from ba_hours

)

select
    cast(scope_type as varchar) as scope_type,
    cast(scope_type || ':' || scope_code as varchar) as scope_id,
    cast(scope_code as varchar) as scope_code,
    cast(period_utc as {{ timestamp_type() }}) as period_utc,
    sum(demand_mwh) as demand_mwh,
    cast(count(*) as integer) as bas_expected,
    cast(count_if(is_demand_reported) as integer) as bas_reported,
    cast(count_if(is_flagged) as integer) as bas_flagged,
    count_if(is_demand_reported) = count(*) as is_complete
from scoped
group by scope_type, scope_code, period_utc
