{{ config(materialized='view') }}
-- By submission month. Clean claim = no first-pass denial code (independent of payment timing).
-- first_pass_denials counts claims with a denial code on first submission, even if later recovered.
-- final_denials counts claims still denied (not recovered).
select
    strftime(submit_date, '%Y-%m') as year_month,
    count(*) as claims_submitted,
    count(*) filter (where denial_code is null) as clean_claims,
    cast(count(*) filter (where denial_code is null) as double) / count(*) as clean_claim_rate,
    count(*) filter (where denial_code is not null) as first_pass_denials,
    cast(count(*) filter (where denial_code is not null) as double) / count(*) as first_pass_denial_rate,
    count(*) filter (where claim_status = 'denied') as final_denials,
    cast(count(*) filter (where claim_status = 'denied') as double) / count(*) as final_denial_rate,
    cast(sum(billed_amount) as double) as billed_total,
    cast(sum(allowed_amount) as double) as allowed_total,
    cast(sum(paid_amount) as double) as paid_total
from {{ ref('fact_claim') }}
group by 1
order by 1
