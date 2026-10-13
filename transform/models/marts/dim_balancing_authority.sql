-- Current attributes per balancing authority: the open version of each BA in the
-- snap_ba_reference snapshot (SCD Type 2). Full history stays in the snapshot.

select
    ba_code,
    ba_name,
    region_code,
    region_name,
    interconnection,
    time_zone,
    eia_time_zone,
    is_generation_only,
    is_active,
    activation_date,
    retirement_date
from {{ ref('snap_ba_reference') }}
where dbt_valid_to is null
