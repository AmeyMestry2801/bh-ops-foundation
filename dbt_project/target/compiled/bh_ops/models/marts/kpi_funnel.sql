
-- Nested patient funnel: each stage is a subset of the one before it.
with pat as (
    select patient_id from "ops"."marts"."dim_patient"
),

scheduled as (
    select distinct patient_id from "ops"."marts"."fact_appointment"
),

completed as (
    select distinct patient_id from "ops"."marts"."fact_appointment" where status = 'completed'
),

claimed as (
    select distinct patient_id from "ops"."marts"."fact_claim"
),

paid as (
    select distinct patient_id from "ops"."marts"."fact_claim" where claim_status = 'paid'
),

stages as (
    select 1 as stage_order, 'Intake completed' as stage, count(*) as patients from pat
    union all
    select 2, 'Appointment scheduled', count(*) from scheduled
    union all
    select 3, 'First visit completed', count(*) from completed
    union all
    select 4, 'Claim submitted', count(*) from claimed
    union all
    select 5, 'Claim paid', count(*) from paid
)

select
    stage_order,
    stage,
    patients,
    cast(patients as double) / first_value(patients) over (order by stage_order) as pct_of_intake,
    cast(patients as double) / lag(patients) over (order by stage_order) as pct_of_prev_stage
from stages
order by stage_order