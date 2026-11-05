
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select clinic_id
from "ops"."marts"."fact_appointment"
where clinic_id is null



  
  
      
    ) dbt_internal_test