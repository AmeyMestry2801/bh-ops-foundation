
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        modality as value_field,
        count(*) as n_records

    from "ops"."marts"."fact_appointment"
    group by modality

)

select *
from all_values
where value_field not in (
    'telehealth','in_person'
)



  
  
      
    ) dbt_internal_test