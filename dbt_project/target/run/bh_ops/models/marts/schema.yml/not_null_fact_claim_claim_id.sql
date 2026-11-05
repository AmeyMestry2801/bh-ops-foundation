
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select claim_id
from "ops"."marts"."fact_claim"
where claim_id is null



  
  
      
    ) dbt_internal_test