-- One row per observation: generation for (BA, fuel, hour) as seen by one ingestion run.
-- Same pattern as stg_eia__region_data: exact duplicates within a load are dropped, loads are
-- never collapsed by hash.

with source as (

    select * from {{ source('eia_raw', 'eia_fuel_type_data') }}

),

renamed as (

    select
        respondent as ba_code,
        fueltype as fuel_code,
        type_name as fuel_name_eia,
        {{ to_utc_timestamp('period_utc') }} as period_utc,
        cast(value as double) as generation_mwh,
        value_units,
        _record_hash as record_hash,
        _run_id as run_id,
        _route as route,
        {{ to_utc_timestamp('_ingested_at') }} as ingested_at_utc,
        _api_version as api_version
    from source

),

deduplicated as (

    select
        *,
        row_number() over (
            partition by record_hash, ingested_at_utc
            order by run_id
        ) as duplicate_rank
    from renamed

)

select
    ba_code,
    fuel_code,
    fuel_name_eia,
    period_utc,
    generation_mwh,
    value_units,
    record_hash,
    run_id,
    route,
    ingested_at_utc,
    api_version
from deduplicated
where duplicate_rank = 1
