
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        experiment_arm as value_field,
        count(*) as n_records

    from "ops"."marts"."dim_patient"
    group by experiment_arm

)

select *
from all_values
where value_field not in (
    'control','arm_a','arm_b'
)



  
  
      
    ) dbt_internal_test