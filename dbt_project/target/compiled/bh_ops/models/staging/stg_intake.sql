select
    intake_id,
    patient_id,
    cast(intake_ts as timestamp) as intake_ts,
    cast(phq9_total as integer) as phq9_total,
    cast(gad7_total as integer) as gad7_total,
    acuity,
    cast(sdoh_housing as integer) as sdoh_housing,
    cast(sdoh_transport as integer) as sdoh_transport,
    cast(sdoh_food as integer) as sdoh_food,
    cast(sdoh_employment as integer) as sdoh_employment
from "ops"."raw"."intake"