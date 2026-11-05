
  
  create view "ops"."marts"."kpi_fill_rate_monthly__dbt_tmp" as (
    
-- Fill rate = booked slots (appointments not cancelled in advance) / assumed capacity.
-- Capacity = sum of provider weekly slots * capacity_multiplier * days_in_month / 7. ASSUMPTION (see docs).
with cap as (
    select cast(sum(weekly_slot_capacity) as double) * 1.7 as weekly_slots
    from "ops"."marts"."dim_provider"
),

days as (
    select year_month, count(*) as days_in_month
    from "ops"."marts"."dim_date"
    group by year_month
),

booked as (
    select
        strftime(appt_date, '%Y-%m') as year_month,
        count(*) filter (where status <> 'cancelled') as booked_slots
    from "ops"."marts"."fact_appointment"
    group by 1
)

select
    b.year_month,
    b.booked_slots,
    c.weekly_slots * d.days_in_month / 7.0 as capacity_slots,
    b.booked_slots / (c.weekly_slots * d.days_in_month / 7.0) as fill_rate
from booked b
join days d on b.year_month = d.year_month
cross join cap c
order by b.year_month
  );
