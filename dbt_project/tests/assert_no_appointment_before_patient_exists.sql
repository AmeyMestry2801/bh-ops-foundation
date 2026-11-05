select f.appointment_id, f.appt_date, p.created_date
from {{ ref('fact_appointment') }} f
join {{ ref('dim_patient') }} p
    on f.patient_id = p.patient_id
where f.appt_date < p.created_date
