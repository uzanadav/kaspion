-- The showcase test: all detected transfer legs must net to ~zero.
-- Fails (returns rows) if transfer detection ever flags unbalanced pairs.
with transfer_amounts as (
    select t.transaction_id, s.amount
    from {{ ref('int_transfers_detected') }} t
    join {{ ref('stg_transactions') }} s using (transaction_id)
)

select 'net' as check_name, sum(amount) as net
from transfer_amounts
having abs(sum(amount)) > 1.0
