
    
    

with child as (
    select patient_id as from_field
    from "ops"."marts"."fact_appointment"
    where patient_id is not null
),

parent as (
    select patient_id as to_field
    from "ops"."marts"."dim_patient"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null


