-- Bank-side monthly card debits (חיוב). NOT pair-matched: the debit equals the
-- card's statement total, not any single transaction. Detected by issuer pattern.
select
    transaction_id,
    account_id,
    posted_date,
    amount,
    raw_description
from {{ ref('stg_transactions') }}
where account_type = 'bank'
  and amount < 0
  and regexp_matches(raw_description, 'חיוב.*(מקס|ישראכרט|כאל|ויזה|אמריקן|לאומי קארד)')
