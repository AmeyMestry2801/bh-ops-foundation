
    
    

with all_values as (

    select
        status as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_prior_authorizations"
    group by status

)

select *
from all_values
where value_field not in (
    'approved','denied','pending'
)


