
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select payer_type
from "ops"."staging"."stg_patients"
where payer_type is null



  
  
      
    ) dbt_internal_test