
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  select
    appointment_id,
    lead_days,
    date_diff('day', cast(scheduled_ts as date), cast(appt_ts as date)) as lead_days_recomputed
from "ops"."staging"."stg_appointments"
where lead_days != date_diff('day', cast(scheduled_ts as date), cast(appt_ts as date))
  
  
      
    ) dbt_internal_test