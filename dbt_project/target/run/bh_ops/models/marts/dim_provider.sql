
    

    create  table
      "ops"."marts"."dim_provider__dbt_tmp"
  
    
    as (
      select provider_id, clinic_id, provider_type, weekly_slot_capacity
from "ops"."staging"."stg_providers"
    );
    
  