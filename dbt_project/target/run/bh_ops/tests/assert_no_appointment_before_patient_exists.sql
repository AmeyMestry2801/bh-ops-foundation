
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  select f.appointment_id, f.appt_date, p.created_date
from "ops"."marts"."fact_appointment" f
join "ops"."marts"."dim_patient" p
    on f.patient_id = p.patient_id
where f.appt_date < p.created_date
  
  
      
    ) dbt_internal_test