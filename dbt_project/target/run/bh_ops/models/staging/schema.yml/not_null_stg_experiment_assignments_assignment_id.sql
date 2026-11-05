
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select assignment_id
from "ops"."staging"."stg_experiment_assignments"
where assignment_id is null



  
  
      
    ) dbt_internal_test