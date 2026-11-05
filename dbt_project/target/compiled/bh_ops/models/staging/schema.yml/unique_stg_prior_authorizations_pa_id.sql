
    
    

select
    pa_id as unique_field,
    count(*) as n_records

from "ops"."staging"."stg_prior_authorizations"
where pa_id is not null
group by pa_id
having count(*) > 1


