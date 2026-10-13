-- One row per observation: flow from one BA to a neighbour for an hour, as seen by one
-- ingestion run. Sign as EIA reports it: positive = from_ba_code exports to to_ba_code.

with source as (

    select * from {{ source('eia_raw', 'eia_interchange_data') }}
    -- Region-to-region flows (EIA's regional sums) are not BA flows; they stay in raw only.
    where
        fromba not in (
            select agg.respondent_code from {{ ref('eia_aggregate_respondents') }} as agg
        )
        and toba not in (
            select agg.respondent_code from {{ ref('eia_aggregate_respondents') }} as agg
        )

),

renamed as (

    select
        fromba as from_ba_code,
        toba as to_ba_code,
        toba_name as to_ba_name,
        {{ to_utc_timestamp('period_utc') }} as period_utc,
        cast(value as double) as interchange_mwh,
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
    from_ba_code,
    to_ba_code,
    to_ba_name,
    period_utc,
    interchange_mwh,
    value_units,
    record_hash,
    run_id,
    route,
    ingested_at_utc,
    api_version
from deduplicated
where duplicate_rank = 1
