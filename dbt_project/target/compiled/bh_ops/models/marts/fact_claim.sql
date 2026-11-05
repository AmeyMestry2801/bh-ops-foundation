-- Grain: one row per claim whose appointment is in fact_appointment.
-- Excluded (quarantined): unknown appointment, or amounts violating paid <= allowed <= billed.
-- is_first_pass_denied = a denial code was recorded on first submission (even if later recovered).
select
    c.claim_id,
    c.appointment_id,
    c.patient_id,
    c.billed_amount,
    c.allowed_amount,
    c.paid_amount,
    c.claim_status,
    c.denial_code,
    c.resubmission_count,
    c.submit_date,
    cast(strftime(c.submit_date, '%Y%m%d') as integer) as submit_date_key,
    c.paid_date,
    case when c.claim_status = 'paid' and c.paid_date is not null
         then date_diff('day', c.submit_date, c.paid_date) end as days_in_ar,
    case when c.denial_code is not null then 1 else 0 end as is_first_pass_denied
from "ops"."staging"."stg_claims" c
join "ops"."marts"."fact_appointment" a
    on c.appointment_id = a.appointment_id
where c.paid_amount <= c.allowed_amount
  and c.allowed_amount <= c.billed_amount