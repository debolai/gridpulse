-- One row per observation: a value for (BA, series, hour) as seen by one ingestion run.
-- Exact duplicates (same version, same load) are dropped. Loads are NOT collapsed by hash:
-- if a value goes A -> B -> A, the latest observation must still win downstream.

with source as (

    select * from {{ source('eia_raw', 'eia_region_data') }}
    -- EIA's regional and US48 sums are not balancing authorities; they stay in raw only.
    where respondent not in (select respondent_code from {{ ref('eia_aggregate_respondents') }})

),

renamed as (

    select
        respondent as ba_code,
        type as series_code,
        type_name as series_name,
        {{ to_utc_timestamp('period_utc') }} as period_utc,
        cast(value as double) as value_mwh,
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
    series_code,
    series_name,
    period_utc,
    value_mwh,
    value_units,
    record_hash,
    run_id,
    route,
    ingested_at_utc,
    api_version
from deduplicated
where duplicate_rank = 1
