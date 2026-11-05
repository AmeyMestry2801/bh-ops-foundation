
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select intake_id
from "ops"."staging"."stg_intake"
where intake_id is null



  
  
      
    ) dbt_internal_test