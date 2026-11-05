
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  select patient_id, payer_type_raw
from "ops"."staging"."stg_patients"
where payer_type = 'Unknown'
  and payer_type_raw is not null
  
  
      
    ) dbt_internal_test