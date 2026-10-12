-- Current attributes per balancing authority. In B1 this is rebuilt from the
-- snap_ba_reference snapshot (SCD Type 2); for now it reads the seed directly.

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
from {{ ref('ba_reference') }}
