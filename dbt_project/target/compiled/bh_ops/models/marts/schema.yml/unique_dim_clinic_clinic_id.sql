
    
    

select
    clinic_id as unique_field,
    count(*) as n_records

from "ops"."marts"."dim_clinic"
where clinic_id is not null
group by clinic_id
having count(*) > 1


