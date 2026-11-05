
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select eligibility_id
from "ops"."staging"."stg_eligibility_checks"
where eligibility_id is null



  
  
      
    ) dbt_internal_test