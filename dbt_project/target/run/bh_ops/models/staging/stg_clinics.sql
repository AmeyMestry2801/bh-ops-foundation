
    

    create  table
      "ops"."staging"."stg_clinics__dbt_tmp"
  
    
    as (
      select
    clinic_id,
    city,
    state,
    timezone
from "ops"."raw"."clinics"
    );
    
  