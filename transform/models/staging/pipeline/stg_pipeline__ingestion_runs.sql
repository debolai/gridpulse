-- One row per extraction attempt. The backfill command may append an attempt again, so keep
-- one row per (run_id, started_at).

with source as (

    select * from {{ source('pipeline_raw', 'ingestion_runs') }}

),

typed as (

    select
        run_id,
        route,
        {{ to_utc_timestamp('started_at') }} as started_at_utc,
        status,
        {{ to_utc_timestamp('window_start_utc') }} as window_start_utc,
        {{ to_utc_timestamp('window_end_utc') }} as window_end_utc,
        scope,
        pages,
        rows_expected,
        rows_received,
        rows_appended,
        duration_seconds,
        error,
        details,
        {{ to_utc_timestamp('_ingested_at') }} as ingested_at_utc
    from source

),

deduplicated as (

    select
        *,
        row_number() over (
            partition by run_id, started_at_utc order by ingested_at_utc desc
        ) as duplicate_rank
    from typed

)

select
    run_id,
    route,
    started_at_utc,
    status,
    window_start_utc,
    window_end_utc,
    scope,
    pages,
    rows_expected,
    rows_received,
    rows_appended,
    duration_seconds,
    error,
    details
from deduplicated
where duplicate_rank = 1
