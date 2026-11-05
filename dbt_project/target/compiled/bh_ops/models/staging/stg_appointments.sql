-- Raw timestamps come in two formats:
--   '2025-01-06 09:30:00'      = clinic-local wall clock, no offset
--   '2025-01-08T15:00:00Z'     = UTC
-- Both are normalized to clinic-local wall-clock time (naive timestamp).

with src as (
    select
        *,
        row_number() over (partition by appointment_id order by appt_ts) as _rn
    from "ops"."raw"."appointments"
),

dedup as (
    select * from src where _rn = 1
),

joined as (
    select
        d.appointment_id,
        d.patient_id,
        d.provider_id,
        d.clinic_id,
        d.scheduled_ts as scheduled_raw,
        d.appt_ts as appt_raw,
        d.lead_days,
        d.modality,
        d.status,
        d.reminder_arm,
        c.timezone as clinic_tz
    from dedup d
    left join "ops"."staging"."stg_clinics" c
        on d.clinic_id = c.clinic_id
)

select
    appointment_id,
    patient_id,
    provider_id,
    clinic_id,
    case
        when scheduled_raw like '%Z'
            then timezone(clinic_tz, timezone('UTC', strptime(scheduled_raw, '%Y-%m-%dT%H:%M:%SZ')))
        else cast(scheduled_raw as timestamp)
    end as scheduled_ts,
    case
        when appt_raw like '%Z'
            then timezone(clinic_tz, timezone('UTC', strptime(appt_raw, '%Y-%m-%dT%H:%M:%SZ')))
        else cast(appt_raw as timestamp)
    end as appt_ts,
    (appt_raw like '%Z') as source_was_utc,
    cast(lead_days as integer) as lead_days,
    modality,
    status,
    reminder_arm
from joined