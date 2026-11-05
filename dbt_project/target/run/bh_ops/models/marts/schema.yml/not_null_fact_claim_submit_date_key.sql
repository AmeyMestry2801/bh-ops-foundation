
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select submit_date_key
from "ops"."marts"."fact_claim"
where submit_date_key is null



  
  
      
    ) dbt_internal_test