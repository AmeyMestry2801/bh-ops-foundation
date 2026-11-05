
    

    create  table
      "ops"."staging"."stg_claims__dbt_tmp"
  
    
    as (
      with src as (
    select
        *,
        row_number() over (partition by claim_id order by submit_date) as _rn
    from "ops"."raw"."claims"
)

select
    claim_id,
    appointment_id,
    patient_id,
    cast(billed_amount as decimal(12, 2)) as billed_amount,
    cast(allowed_amount as decimal(12, 2)) as allowed_amount,
    cast(paid_amount as decimal(12, 2)) as paid_amount,
    claim_status,
    denial_code,
    cast(resubmission_count as integer) as resubmission_count,
    cast(submit_date as date) as submit_date,
    cast(paid_date as date) as paid_date
from src
where _rn = 1
    );
    
  