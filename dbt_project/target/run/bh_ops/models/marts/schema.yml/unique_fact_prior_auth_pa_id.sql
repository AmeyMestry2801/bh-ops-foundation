
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    pa_id as unique_field,
    count(*) as n_records

from "ops"."marts"."fact_prior_auth"
where pa_id is not null
group by pa_id
having count(*) > 1



  
  
      
    ) dbt_internal_test