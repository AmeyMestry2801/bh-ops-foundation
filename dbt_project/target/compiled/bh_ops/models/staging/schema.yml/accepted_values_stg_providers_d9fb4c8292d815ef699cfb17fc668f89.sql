
    
    

with all_values as (

    select
        provider_type as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_providers"
    group by provider_type

)

select *
from all_values
where value_field not in (
    'psychiatrist','NP','therapist'
)


