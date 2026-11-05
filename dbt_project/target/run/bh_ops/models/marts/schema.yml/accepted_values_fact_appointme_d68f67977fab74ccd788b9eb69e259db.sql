
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        reminder_arm as value_field,
        count(*) as n_records

    from "ops"."marts"."fact_appointment"
    group by reminder_arm

)

select *
from all_values
where value_field not in (
    'standard','control','arm_a','arm_b'
)



  
  
      
    ) dbt_internal_test