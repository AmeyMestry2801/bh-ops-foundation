
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    appointment_id as unique_field,
    count(*) as n_records

from "ops"."marts"."fact_appointment"
where appointment_id is not null
group by appointment_id
having count(*) > 1



  
  
      
    ) dbt_internal_test