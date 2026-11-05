select clinic_id, city, state, timezone
from {{ ref('stg_clinics') }}
