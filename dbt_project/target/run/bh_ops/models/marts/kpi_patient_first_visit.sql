
  
  create view "ops"."marts"."kpi_patient_first_visit__dbt_tmp" as (
    
-- Grain: one row per patient. Days from intake date to first COMPLETED visit (NULL if none yet).
with first_visit as (
    select patient_id, min(appt_date) as first_visit_date
    from "ops"."marts"."fact_appointment"
    where status = 'completed'
    group by patient_id
)

select
    p.patient_id,
    cast(p.intake_ts as date) as intake_date,
    strftime(cast(p.intake_ts as date), '%Y-%m') as intake_month,
    p.payer_type,
    p.acuity,
    fv.first_visit_date,
    date_diff('day', cast(p.intake_ts as date), fv.first_visit_date) as days_intake_to_first_visit
from "ops"."marts"."dim_patient" p
left join first_visit fv
    on p.patient_id = fv.patient_id
  );
