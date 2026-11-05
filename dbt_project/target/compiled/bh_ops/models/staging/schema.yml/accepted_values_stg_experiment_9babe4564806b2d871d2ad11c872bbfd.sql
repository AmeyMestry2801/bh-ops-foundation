
    
    

with all_values as (

    select
        arm as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_experiment_assignments"
    group by arm

)

select *
from all_values
where value_field not in (
    'control','arm_a','arm_b'
)


