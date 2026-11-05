{{ config(materialized='view') }}
-- Days in A/R = paid_date - submit_date for PAID claims, grouped by the month the claim was paid.
select
    strftime(paid_date, '%Y-%m') as year_month,
    count(*) as paid_claims,
    avg(days_in_ar) as mean_days_in_ar,
    median(days_in_ar) as median_days_in_ar
from {{ ref('fact_claim') }}
where claim_status = 'paid' and paid_date is not null
group by 1
order by 1
