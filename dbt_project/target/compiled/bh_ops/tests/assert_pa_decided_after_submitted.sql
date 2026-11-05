select pa_id, submitted_ts, decided_ts
from "ops"."marts"."fact_prior_auth"
where decided_ts is not null
  and decided_ts < submitted_ts