-- No bank-side card debit may ever appear in fct_spend.
select f.transaction_id
from {{ ref('fct_spend') }} f
join {{ ref('int_card_payments') }} c using (transaction_id)
