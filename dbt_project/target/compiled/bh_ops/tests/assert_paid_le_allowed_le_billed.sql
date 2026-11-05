select claim_id, billed_amount, allowed_amount, paid_amount
from "ops"."marts"."fact_claim"
where paid_amount > allowed_amount
   or allowed_amount > billed_amount