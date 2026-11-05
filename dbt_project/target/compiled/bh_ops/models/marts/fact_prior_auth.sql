-- Grain: one row per prior-auth request with a known patient.
-- SLA thresholds are an ASSUMPTION borrowed from the CMS-0057-F public rule
-- (72h urgent / 7 calendar days standard); not a claim about behavioral-health payers.
-- Pending requests (no decision yet) have NULL turnaround and NULL breach flag.
select
    pa.pa_id,
    pa.patient_id,
    pa.submitted_ts,
    pa.decided_ts,
    pa.urgency,
    pa.status,
    pa.denial_reason,
    case when pa.decided_ts is not null
         then cast(date_diff('second', pa.submitted_ts, pa.decided_ts) as double) / 3600.0 end as turnaround_hours,
    case when pa.urgency = 'urgent' then 72 else 168 end as sla_threshold_hours,
    case
        when pa.decided_ts is null then null
        when cast(date_diff('second', pa.submitted_ts, pa.decided_ts) as double) / 3600.0
             > case when pa.urgency = 'urgent' then 72 else 168 end then 1
        else 0
    end as is_sla_breach
from "ops"."staging"."stg_prior_authorizations" pa
join "ops"."staging"."stg_patients" p
    on pa.patient_id = p.patient_id