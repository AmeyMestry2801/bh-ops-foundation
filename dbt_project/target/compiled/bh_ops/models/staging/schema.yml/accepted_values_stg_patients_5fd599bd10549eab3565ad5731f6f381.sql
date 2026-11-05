
    
    

with all_values as (

    select
        age_band as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_patients"
    group by age_band

)

select *
from all_values
where value_field not in (
    '18-24','25-34','35-49','50-64','65+'
)


