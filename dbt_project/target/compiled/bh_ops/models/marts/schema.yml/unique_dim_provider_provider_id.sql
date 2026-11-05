
    
    

select
    provider_id as unique_field,
    count(*) as n_records

from "ops"."marts"."dim_provider"
where provider_id is not null
group by provider_id
having count(*) > 1


