-- Grain: one row per valid appointment.
-- Excluded (quarantined, counted in reports/dq_report.md): unknown patient, unknown provider,
-- or appointment dated before the patient record was created.
select
    a.appointment_id,
    a.patient_id,
    a.provider_id,
    a.clinic_id,
    cast(a.appt_ts as date) as appt_date,
    cast(strftime(a.appt_ts, '%Y%m%d') as integer) as date_key,
    a.scheduled_ts,
    a.appt_ts,
    hour(a.appt_ts) as appt_hour,
    isodow(a.appt_ts) as appt_dow,
    a.lead_days,
    case
        when a.lead_days <= 1 then '0-1'
        when a.lead_days <= 7 then '2-7'
        when a.lead_days <= 14 then '8-14'
        when a.lead_days <= 21 then '15-21'
        when a.lead_days <= 30 then '22-30'
        else '31+'
    end as lead_bucket,
    a.modality,
    a.status,
    a.reminder_arm,
    case when a.status = 'no_show' then 1 else 0 end as is_no_show,
    case when a.status = 'late_cancel' then 1 else 0 end as is_late_cancel,
    case when a.status = 'cancelled' then 1 else 0 end as is_cancelled,
    case when a.status = 'completed' then 1 else 0 end as is_completed,
    case when a.status in ('completed', 'no_show', 'late_cancel') then 1 else 0 end as is_resolved
from {{ ref('stg_appointments') }} a
join {{ ref('stg_patients') }} p
    on a.patient_id = p.patient_id
join {{ ref('stg_providers') }} v
    on a.provider_id = v.provider_id
where cast(a.appt_ts as date) >= p.created_date
