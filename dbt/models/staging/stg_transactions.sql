with src as (
    select * from {{ source('raw', 'transactions') }}
)

select
    transaction_id,
    account_id,
    account_type,
    posted_date,
    date_trunc('month', posted_date)                          as posted_month,
    amount,
    currency,
    trim(raw_description)                                     as raw_description,
    -- normalized merchant key: strip trailing branch/store numbers, collapse spaces
    trim(regexp_replace(
        regexp_replace(lower(trim(raw_description)), '\s+\d+$', ''),
        '\s+', ' ', 'g'
    ))                                                        as merchant_key,
    source,
    ingested_at
from src
