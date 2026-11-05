
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    provider_id as unique_field,
    count(*) as n_records

from "ops"."staging"."stg_providers"
where provider_id is not null
group by provider_id
having count(*) > 1



  
  
      
    ) dbt_internal_test