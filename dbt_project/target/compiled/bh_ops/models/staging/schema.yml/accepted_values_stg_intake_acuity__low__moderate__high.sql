
    
    

with all_values as (

    select
        acuity as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_intake"
    group by acuity

)

select *
from all_values
where value_field not in (
    'low','moderate','high'
)


