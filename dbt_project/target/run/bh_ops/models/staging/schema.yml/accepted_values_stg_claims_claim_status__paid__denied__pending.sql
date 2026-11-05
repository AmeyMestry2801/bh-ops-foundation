
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        claim_status as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_claims"
    group by claim_status

)

select *
from all_values
where value_field not in (
    'paid','denied','pending'
)



  
  
      
    ) dbt_internal_test