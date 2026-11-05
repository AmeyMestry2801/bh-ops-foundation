
    
    

with all_values as (

    select
        reminder_arm as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_appointments"
    group by reminder_arm

)

select *
from all_values
where value_field not in (
    'standard','control','arm_a','arm_b'
)


