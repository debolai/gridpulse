-- One row per EIA fuel code (seed `fuel_type_map`). EIA labels some codes inconsistently
-- (PS is "Pumped storage" and "Pumped Storage"; BAT is "Battery" and "Battery storage"), so the
-- seed, keyed on the code, is the single source of fuel names.

select
    cast(fuel_code as varchar) as fuel_code,
    cast(fuel_name as varchar) as fuel_name,
    cast(fuel_category as varchar) as fuel_category,
    cast(is_renewable as boolean) as is_renewable,
    cast(is_storage as boolean) as is_storage
from {{ ref('fuel_type_map') }}
