
    
    

select
    intake_id as unique_field,
    count(*) as n_records

from "ops"."staging"."stg_intake"
where intake_id is not null
group by intake_id
having count(*) > 1


