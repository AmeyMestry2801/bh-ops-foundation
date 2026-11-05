
-- Revenue leakage = allowed amount on claims that are denied (unrecovered) or still unpaid more than 90 days
-- after submission, / total allowed. Only months through leakage_max_month (all claims >= 90 days old as of
-- the data end date 2026-06-30), so every 'pending' claim here is genuinely past 90 days.
select
    strftime(submit_date, '%Y-%m') as year_month,
    count(*) as claims,
    cast(sum(allowed_amount) as double) as allowed_total,
    cast(sum(case when claim_status = 'denied' then allowed_amount else 0 end) as double) as leaked_denied,
    cast(sum(case when claim_status = 'pending' then allowed_amount else 0 end) as double) as leaked_unpaid_90d,
    cast(sum(case when claim_status in ('denied', 'pending') then allowed_amount else 0 end) as double)
        / cast(sum(allowed_amount) as double) as leakage_rate
from "ops"."marts"."fact_claim"
where strftime(submit_date, '%Y-%m') <= '2026-03'
group by 1
order by 1