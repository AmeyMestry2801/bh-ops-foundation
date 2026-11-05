
    
    

select
    patient_id as unique_field,
    count(*) as n_records

from "ops"."staging"."stg_experiment_assignments"
where patient_id is not null
group by patient_id
having count(*) > 1


