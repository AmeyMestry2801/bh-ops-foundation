
  
  create view "ops"."marts"."kpi_prior_auth_monthly__dbt_tmp" as (
    
-- By submission month and urgency. Breach and denial rates use DECIDED requests only (pending excluded).
-- SLA thresholds: ASSUMPTION borrowed from CMS-0057-F (72h urgent / 7 calendar days standard).
select
    strftime(submitted_ts, '%Y-%m') as year_month,
    urgency,
    count(*) as requests,
    count(decided_ts) as decided,
    count(*) filter (where is_sla_breach = 1) as sla_breaches,
    cast(count(*) filter (where is_sla_breach = 1) as double) / nullif(count(decided_ts), 0) as sla_breach_rate,
    avg(turnaround_hours) as mean_turnaround_hours,
    median(turnaround_hours) as median_turnaround_hours,
    count(*) filter (where status = 'denied') as denied,
    cast(count(*) filter (where status = 'denied') as double) / nullif(count(decided_ts), 0) as denial_rate
from "ops"."marts"."fact_prior_auth"
group by 1, 2
order by 1, 2
  );
