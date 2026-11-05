with src as (
    select
        *,
        row_number() over (partition by patient_id order by created_date) as _rn
    from {{ source('raw', 'patients') }}
),

dedup as (
    select
        patient_id,
        clinic_id,
        created_date,
        age_band,
        payer_type as payer_type_raw,
        language,
        prior_no_show_count
    from src
    where _rn = 1
),

keyed as (
    select
        *,
        lower(regexp_replace(trim(payer_type_raw), '[^A-Za-z]', '', 'g')) as _payer_key
    from dedup
)

select
    patient_id,
    clinic_id,
    cast(created_date as date) as created_date,
    age_band,
    payer_type_raw,
    case
        when _payer_key in ('medicaid', 'mcaid') then 'Medicaid'
        when _payer_key in ('medicare', 'mcare') then 'Medicare'
        when _payer_key in ('commercial', 'comm') then 'Commercial'
        when _payer_key = 'selfpay' then 'Self-pay'
        else 'Unknown'
    end as payer_type,
    language,
    cast(prior_no_show_count as integer) as prior_no_show_count
from keyed
