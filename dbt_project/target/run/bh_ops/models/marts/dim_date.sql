
    

    create  table
      "ops"."marts"."dim_date__dbt_tmp"
  
    
    as (
      with days as (
    select cast(d as date) as date_day
    from generate_series(date '2025-01-01', date '2026-12-31', interval 1 day) as t(d)
)

select
    cast(strftime(date_day, '%Y%m%d') as integer) as date_key,
    date_day,
    year(date_day) as cal_year,
    quarter(date_day) as cal_quarter,
    month(date_day) as cal_month,
    strftime(date_day, '%Y-%m') as year_month,
    monthname(date_day) as month_name,
    isodow(date_day) as day_of_week,
    dayname(date_day) as day_name,
    case when isodow(date_day) >= 6 then 1 else 0 end as is_weekend
from days
    );
    
  