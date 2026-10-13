-- Typed GHCNh temperature reports, latest load per report. Grain: station × observation
-- time × report type.
-- temperature_passed_qc follows NOAA's GHCNh documentation (ghcnh_DOCUMENTATION.pdf):
-- lower-case letters are GHCNh's own failed checks (spike, streak, outlier, ...); legacy
-- source codes 2/6 are suspect and 3/7 erroneous. Blank, 0, 1, 4, 5, 9 and the accepted or
-- corrected codes (A, U, P, ...) pass. Failed readings are kept and flagged, never dropped.

with source as (

    select * from {{ source('noaa_raw', 'noaa_ghcnh_observations') }}

),

typed as (

    select
        station_id,
        station_name,
        {{ to_utc_timestamp('observed_at_utc') }} as observed_at_utc,
        coalesce(report_type, 'unknown') as report_type,
        temperature_c,
        temperature_quality_code,
        dew_point_c,
        wind_speed_ms,
        relative_humidity_pct,
        _record_hash as record_hash,
        _run_id as run_id,
        {{ to_utc_timestamp('_ingested_at') }} as ingested_at_utc
    from source

),

latest as (

    select
        *,
        row_number() over (
            partition by station_id, observed_at_utc, report_type
            order by ingested_at_utc desc, record_hash asc
        ) as recency_rank
    from typed

)

select
    station_id,
    station_name,
    observed_at_utc,
    report_type,
    temperature_c,
    temperature_quality_code,
    coalesce(
        not (
            regexp_like(temperature_quality_code, '^[a-z]$')
            or temperature_quality_code in ('2', '3', '6', '7')
        ),
        true
    ) as temperature_passed_qc,
    dew_point_c,
    wind_speed_ms,
    relative_humidity_pct,
    record_hash,
    run_id,
    ingested_at_utc
from latest
where recency_rank = 1
