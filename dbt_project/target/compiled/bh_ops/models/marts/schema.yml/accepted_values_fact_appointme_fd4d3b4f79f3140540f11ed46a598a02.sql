
    
    

with all_values as (

    select
        lead_bucket as value_field,
        count(*) as n_records

    from "ops"."marts"."fact_appointment"
    group by lead_bucket

)

select *
from all_values
where value_field not in (
    '0-1','2-7','8-14','15-21','22-30','31+'
)


