-- Pipeline runs: what each extraction attempt asked for, what it got and how long it took.
-- "running" means the process died before finishing (its manifest was never completed).

select
    cast(run_id as varchar) as run_id,
    cast(route as varchar) as route,
    cast(started_at_utc as {{ timestamp_type() }}) as started_at_utc,
    cast(status as varchar) as status,
    cast(window_start_utc as {{ timestamp_type() }}) as window_start_utc,
    cast(window_end_utc as {{ timestamp_type() }}) as window_end_utc,
    cast(scope as varchar) as scope,
    cast(pages as bigint) as pages,
    cast(rows_expected as bigint) as rows_expected,
    cast(rows_received as bigint) as rows_received,
    cast(rows_appended as bigint) as rows_appended,
    -- EIA reports a total to check against; NOAA has none, so a NOAA run is complete when
    -- everything it read was appended.
    coalesce(
        status = 'succeeded'
        and rows_received = coalesce(rows_expected, rows_received)
        and rows_appended = rows_received,
        false
    ) as is_complete,
    duration_seconds,
    cast(error as varchar) as error,
    cast(details as varchar) as details
from {{ ref('stg_pipeline__ingestion_runs') }}
