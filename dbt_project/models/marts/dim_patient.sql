-- Grain: one row per patient. Intake scores/flags and experiment arm are attached here.
-- payer_type = 'Unknown' marks patients whose payer was missing in the source.
select
    p.patient_id,
    p.clinic_id,
    p.created_date,
    p.age_band,
    p.payer_type,
    p.language,
    p.prior_no_show_count,
    i.intake_ts,
    i.phq9_total,
    i.gad7_total,
    i.acuity,
    i.sdoh_housing,
    i.sdoh_transport,
    i.sdoh_food,
    i.sdoh_employment,
    x.arm as experiment_arm
from {{ ref('stg_patients') }} p
left join {{ ref('stg_intake') }} i
    on p.patient_id = i.patient_id
left join {{ ref('stg_experiment_assignments') }} x
    on p.patient_id = x.patient_id
