
    
    

with child as (
    select clinic_id as from_field
    from "ops"."staging"."stg_providers"
    where clinic_id is not null
),

parent as (
    select clinic_id as to_field
    from "ops"."staging"."stg_clinics"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null


