
  
  create view "ops"."marts"."kpi_access_monthly__dbt_tmp" as (
    
-- By intake month. Later cohorts have less follow-up time (right-censoring), so recent months look worse.
select
    intake_month as year_month,
    count(*) as intakes,
    count(first_visit_date) as patients_with_first_visit,
    cast(count(first_visit_date) as double) / count(*) as first_visit_rate,
    avg(days_intake_to_first_visit) as mean_days,
    median(days_intake_to_first_visit) as median_days,
    cast(count(*) filter (where days_intake_to_first_visit <= 14) as double)
        / nullif(count(first_visit_date), 0) as pct_within_14d
from "ops"."marts"."kpi_patient_first_visit"
group by intake_month
order by intake_month
  );
