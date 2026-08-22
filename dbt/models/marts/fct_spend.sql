-- One row per REAL spend transaction: outflows only, transfers and
-- bank-side card debits excluded (the card-side charges are the real spend).
select
    transaction_id,
    account_id,
    account_type,
    posted_date,
    posted_month,
    amount,
    abs(amount)      as spend_ils,
    raw_description,
    merchant_key,
    category_id,
    category_source
from {{ ref('int_categorized') }}
where amount < 0
  and not is_transfer
  and not is_card_payment
  -- a charge that came back is not spending. Its credit leg is filtered out too (it is
  -- positive, and this model is outflows only), so the pair nets to zero rather than
  -- landing as a negative category total.
  and not is_refunded
  -- owner-hidden transactions (via dashboard/CLI) never count as spend
  and transaction_id not in (
      select transaction_id from {{ source('state', 'excluded_transactions') }}
  )
