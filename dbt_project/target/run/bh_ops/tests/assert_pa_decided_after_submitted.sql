
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  select pa_id, submitted_ts, decided_ts
from "ops"."marts"."fact_prior_auth"
where decided_ts is not null
  and decided_ts < submitted_ts
  
  
      
    ) dbt_internal_test