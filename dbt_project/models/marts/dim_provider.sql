select provider_id, clinic_id, provider_type, weekly_slot_capacity
from {{ ref('stg_providers') }}
