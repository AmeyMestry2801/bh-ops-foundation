
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        status as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_prior_authorizations"
    group by status

)

select *
from all_values
where value_field not in (
    'approved','denied','pending'
)



  
  
      
    ) dbt_internal_test