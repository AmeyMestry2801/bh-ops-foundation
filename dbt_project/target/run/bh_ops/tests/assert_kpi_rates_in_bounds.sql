
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  select 'appointments' as src, year_month from "ops"."marts"."kpi_appointments_monthly"
where no_show_rate not between 0 and 1 or late_cancel_rate not between 0 and 1
union all
select 'claims', year_month from "ops"."marts"."kpi_claims_monthly"
where clean_claim_rate not between 0 and 1
   or first_pass_denial_rate not between 0 and 1
   or final_denial_rate not between 0 and 1
union all
select 'leakage', year_month from "ops"."marts"."kpi_leakage_monthly"
where leakage_rate not between 0 and 1
  
  
      
    ) dbt_internal_test