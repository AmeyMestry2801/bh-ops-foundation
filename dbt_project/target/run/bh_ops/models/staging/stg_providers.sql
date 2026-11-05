
    

    create  table
      "ops"."staging"."stg_providers__dbt_tmp"
  
    
    as (
      select
    provider_id,
    clinic_id,
    provider_type,
    cast(weekly_slot_capacity as integer) as weekly_slot_capacity
from "ops"."raw"."providers"
    );
    
  