
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    eligibility_id as unique_field,
    count(*) as n_records

from "ops"."staging"."stg_eligibility_checks"
where eligibility_id is not null
group by eligibility_id
having count(*) > 1



  
  
      
    ) dbt_internal_test