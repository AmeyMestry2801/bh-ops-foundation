
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        provider_type as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_providers"
    group by provider_type

)

select *
from all_values
where value_field not in (
    'psychiatrist','NP','therapist'
)



  
  
      
    ) dbt_internal_test