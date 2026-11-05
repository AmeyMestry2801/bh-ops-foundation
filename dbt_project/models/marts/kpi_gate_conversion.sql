{{ config(materialized='view') }}
-- Where do patients drop out? Share who ever get scheduled, split by the eligibility and prior-auth gates.
-- eligibility_gate: 'blocked' = latest check inactive / pending_info.
-- pa_gate: no_pa_needed (no request) / pa_not_denied (approved or pending) / pa_denied.
with elig as (
    select patient_id, eligibility_status
    from (
        select
            patient_id,
            eligibility_status,
            row_number() over (partition by patient_id order by checked_ts desc, eligibility_id desc) as rn
        from {{ ref('stg_eligibility_checks') }}
    ) t
    where rn = 1
),

pa as (
    select patient_id, max(case when status = 'denied' then 1 else 0 end) as pa_denied
    from {{ ref('fact_prior_auth') }}
    group by patient_id
),

sched as (
    select distinct patient_id from {{ ref('fact_appointment') }}
),

base as (
    select
        p.patient_id,
        case when e.eligibility_status in ('inactive', 'pending_info') then 'blocked' else 'clear' end as eligibility_gate,
        case
            when pa.patient_id is null then 'no_pa_needed'
            when pa.pa_denied = 1 then 'pa_denied'
            else 'pa_not_denied'
        end as pa_gate,
        case when s.patient_id is not null then 1 else 0 end as scheduled
    from {{ ref('dim_patient') }} p
    left join elig e on p.patient_id = e.patient_id
    left join pa on p.patient_id = pa.patient_id
    left join sched s on p.patient_id = s.patient_id
)

select
    eligibility_gate,
    pa_gate,
    count(*) as patients,
    count(*) filter (where scheduled = 1) as scheduled_patients,
    cast(count(*) filter (where scheduled = 1) as double) / count(*) as scheduled_rate
from base
group by eligibility_gate, pa_gate
order by eligibility_gate, pa_gate
