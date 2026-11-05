select
    pa_id,
    patient_id,
    cast(submitted_ts as timestamp) as submitted_ts,
    cast(decided_ts as timestamp) as decided_ts,
    urgency,
    status,
    denial_reason
from {{ source('raw', 'prior_authorizations') }}
