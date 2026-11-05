
    
    

with all_values as (

    select
        payer_type as value_field,
        count(*) as n_records

    from "ops"."staging"."stg_patients"
    group by payer_type

)

select *
from all_values
where value_field not in (
    'Medicaid','Medicare','Commercial','Self-pay','Unknown'
)


