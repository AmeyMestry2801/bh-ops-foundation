select pa_id, submitted_ts, decided_ts
from {{ ref('fact_prior_auth') }}
where decided_ts is not null
  and decided_ts < submitted_ts
