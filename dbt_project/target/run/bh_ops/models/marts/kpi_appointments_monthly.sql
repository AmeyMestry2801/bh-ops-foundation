
  
  create view "ops"."marts"."kpi_appointments_monthly__dbt_tmp" as (
    
-- No-show and late-cancel rate: denominator = resolved appointments (completed + no_show + late_cancel).
select
    strftime(appt_date, '%Y-%m') as year_month,
    count(*) as appointments_scheduled,
    count(*) filter (where is_resolved = 1) as resolved,
    count(*) filter (where status = 'completed') as completed,
    count(*) filter (where status = 'no_show') as no_shows,
    count(*) filter (where status = 'late_cancel') as late_cancels,
    count(*) filter (where status = 'cancelled') as cancelled,
    cast(count(*) filter (where status = 'no_show') as double)
        / nullif(count(*) filter (where is_resolved = 1), 0) as no_show_rate,
    cast(count(*) filter (where status = 'late_cancel') as double)
        / nullif(count(*) filter (where is_resolved = 1), 0) as late_cancel_rate
from "ops"."marts"."fact_appointment"
group by 1
order by 1
  );
