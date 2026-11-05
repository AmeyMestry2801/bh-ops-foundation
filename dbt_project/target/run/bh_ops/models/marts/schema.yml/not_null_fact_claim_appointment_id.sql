
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select appointment_id
from "ops"."marts"."fact_claim"
where appointment_id is null



  
  
      
    ) dbt_internal_test