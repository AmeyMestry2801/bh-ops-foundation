
    
    

with all_values as (

    select
        status as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_appointments"
    group by status

)

select *
from all_values
where value_field not in (
    'completed','no_show','cancelled','late_cancel'
)


