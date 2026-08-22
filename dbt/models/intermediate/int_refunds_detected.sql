-- A charge and its refund: same account, opposite sign, same amount, credit within 45
-- days. Both legs are money that never left the household, so neither is spending and
-- the credit is certainly not income — a ₪40 דמי מנוי refunded two days later must not
-- read as ₪40 earned.
--
-- Same 1:1 pairing as int_transfers_detected (a charge refunded once cannot also refund
-- a second charge), and the same reason for it: without the two row_number()s a single
-- ₪17.90 card fee matches every ₪17.90 credit in the window and nets out three months
-- of fees against one charge.
--
-- 45 days, not 3 like transfers: a card fee waiver arrives on the NEXT billing cycle
-- (observed 25-26 days later), while a direct-debit reversal lands within 2.
--
-- ponytail: matched on amount alone, so a genuine charge that happens to equal an
-- unrelated credit in the same window pairs by coincidence (seen once: a ₪5 ticket
-- against a ₪5 card-fee waiver). Add a merchant_key or category check if that ever
-- costs more than pocket change.
with txns as (
    select * from {{ ref('stg_transactions') }}
),

pairs as (
    select
        c.transaction_id as charge_id,
        d.transaction_id as credit_id,
        row_number() over (
            partition by c.transaction_id
            order by date_diff('day', c.posted_date, d.posted_date), d.transaction_id
        ) as rn_charge,
        row_number() over (
            partition by d.transaction_id
            order by date_diff('day', c.posted_date, d.posted_date), c.transaction_id
        ) as rn_credit
    from txns c
    join txns d
      on c.account_id = d.account_id
     and c.amount < 0
     and d.amount > 0
     and abs(c.amount + d.amount) < 0.01
     -- the credit must FOLLOW the charge: a credit that precedes it refunds something
     -- older, usually the same fee one cycle back, and pairing them would be backwards
     and date_diff('day', c.posted_date, d.posted_date) between 0 and 45
),

matched as (
    select charge_id, credit_id from pairs where rn_charge = 1 and rn_credit = 1
)

select charge_id as transaction_id, credit_id as counterpart_id, true as is_charge_leg
from matched
union all
select credit_id as transaction_id, charge_id as counterpart_id, false as is_charge_leg
from matched
