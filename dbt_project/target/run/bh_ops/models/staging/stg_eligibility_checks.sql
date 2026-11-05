
    

    create  table
      "ops"."staging"."stg_eligibility_checks__dbt_tmp"
  
    
    as (
      with src as (
    select
        *,
        row_number() over (partition by eligibility_id order by checked_ts) as _rn
    from "ops"."raw"."eligibility_checks"
)

select
    eligibility_id,
    patient_id,
    cast(checked_ts as timestamp) as checked_ts,
    payer_type_checked,
    eligibility_status
from src
where _rn = 1
    );
    
  