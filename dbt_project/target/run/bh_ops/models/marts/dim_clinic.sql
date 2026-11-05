
    

    create  table
      "ops"."marts"."dim_clinic__dbt_tmp"
  
    
    as (
      select clinic_id, city, state, timezone
from "ops"."staging"."stg_clinics"
    );
    
  