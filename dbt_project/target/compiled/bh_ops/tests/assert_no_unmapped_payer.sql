select patient_id, payer_type_raw
from "ops"."staging"."stg_patients"
where payer_type = 'Unknown'
  and payer_type_raw is not null