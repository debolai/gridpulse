-- No code in seed eia_aggregate_respondents may also be a balancing authority: staging drops
-- aggregate codes, so an overlap would silently remove a real BA. Returns overlapping codes.
select agg.respondent_code
from {{ ref('eia_aggregate_respondents') }} as agg
inner join {{ ref('ba_reference') }} as ba
    on agg.respondent_code = ba.ba_code
