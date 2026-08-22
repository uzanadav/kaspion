-- Each leg of a refund pair belongs to exactly one pair, and no row is both a refund
-- and a transfer. Without the two row_number()s in int_refunds_detected a single ₪17.90
-- card fee matches every ₪17.90 credit in the 45-day window, netting three months of
-- fees against one charge and quietly deleting real spending from the totals.
select transaction_id, count(*) as legs
from {{ ref('int_refunds_detected') }}
group by 1
having count(*) > 1

union all

select r.transaction_id, 2
from {{ ref('int_refunds_detected') }} r
join {{ ref('int_transfers_detected') }} t using (transaction_id)
