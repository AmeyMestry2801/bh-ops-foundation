select
    appointment_id,
    lead_days,
    date_diff('day', cast(scheduled_ts as date), cast(appt_ts as date)) as lead_days_recomputed
from "ops"."staging"."stg_appointments"
where lead_days != date_diff('day', cast(scheduled_ts as date), cast(appt_ts as date))