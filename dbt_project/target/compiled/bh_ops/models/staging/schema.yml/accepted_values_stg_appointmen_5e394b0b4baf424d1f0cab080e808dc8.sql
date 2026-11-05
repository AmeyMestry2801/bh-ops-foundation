
    
    

with all_values as (

    select
        modality as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_appointments"
    group by modality

)

select *
from all_values
where value_field not in (
    'telehealth','in_person'
)


