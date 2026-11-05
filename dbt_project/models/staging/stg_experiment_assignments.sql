select
    assignment_id,
    patient_id,
    arm,
    cast(assigned_date as date) as assigned_date
from {{ source('raw', 'experiment_assignments') }}
