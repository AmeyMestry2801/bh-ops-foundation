
    
    

with all_values as (

    select
        status as value_field,
        count(*) as n_records

    from "ops"."marts"."fact_prior_auth"
    group by status

)

select *
from all_values
where value_field not in (
    'approved','denied','pending'
)


