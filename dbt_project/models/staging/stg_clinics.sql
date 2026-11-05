select
    clinic_id,
    city,
    state,
    timezone
from {{ source('raw', 'clinics') }}
