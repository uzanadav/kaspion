-- A card is debited once a month. A second row for the same card in the same month
-- means the issuer-name match swallowed something that is not a statement debit —
-- a card fee, most often — and dropped real spending out of every total silently.
select account_id, raw_description, date_trunc('month', posted_date) as m, count(*) as n
from {{ ref('int_card_payments') }}
group by 1, 2, 3
having count(*) > 1
