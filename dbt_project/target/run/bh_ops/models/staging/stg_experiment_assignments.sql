
    

    create  table
      "ops"."staging"."stg_experiment_assignments__dbt_tmp"
  
    
    as (
      select
    assignment_id,
    patient_id,
    arm,
    cast(assigned_date as date) as assigned_date
from "ops"."raw"."experiment_assignments"
    );
    
  