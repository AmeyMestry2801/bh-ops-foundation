
    
    

with all_values as (

    select
        urgency as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_prior_authorizations"
    group by urgency

)

select *
from all_values
where value_field not in (
    'urgent','standard'
)


