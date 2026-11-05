{{ config(materialized='view') }}
-- First-pass denials by payer and denial code. Code labels are short plain-language paraphrases.
-- recovered_claims = first-pass denied claims that ended 'paid' after resubmission.
with c as (
    select f.claim_id, f.claim_status, f.denial_code, f.allowed_amount, p.payer_type
    from {{ ref('fact_claim') }} f
    join {{ ref('dim_patient') }} p
        on f.patient_id = p.patient_id
),

tot as (
    select payer_type, count(*) as payer_claims
    from c
    group by payer_type
),

den as (
    select
        payer_type,
        denial_code,
        count(*) as denied_claims,
        count(*) filter (where claim_status = 'paid') as recovered_claims,
        cast(sum(allowed_amount) as double) as allowed_amount_denied
    from c
    where denial_code is not null
    group by payer_type, denial_code
)

select
    d.payer_type,
    d.denial_code,
    case d.denial_code
        when 'CO-16' then 'Missing info / billing error'
        when 'CO-50' then 'Not medically necessary'
        when 'CO-27' then 'Coverage terminated'
        when 'CO-29' then 'Timely filing expired'
        when 'CO-4' then 'Procedure / modifier mismatch'
        when 'CO-18' then 'Duplicate claim'
        when 'CO-197' then 'Prior authorization absent'
        else 'Other'
    end as denial_reason,
    t.payer_claims,
    d.denied_claims,
    cast(d.denied_claims as double) / t.payer_claims as denial_rate,
    d.recovered_claims,
    d.allowed_amount_denied
from den d
join tot t on d.payer_type = t.payer_type
order by d.payer_type, d.denied_claims desc
