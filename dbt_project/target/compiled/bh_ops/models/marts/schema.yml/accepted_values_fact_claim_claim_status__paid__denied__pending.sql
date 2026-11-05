
    
    

with all_values as (

    select
        claim_status as value_field,
        count(*) as n_records

    from "ops"."marts"."fact_claim"
    group by claim_status

)

select *
from all_values
where value_field not in (
    'paid','denied','pending'
)


