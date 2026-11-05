
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select pa_id
from "ops"."marts"."fact_prior_auth"
where pa_id is null



  
  
      
    ) dbt_internal_test