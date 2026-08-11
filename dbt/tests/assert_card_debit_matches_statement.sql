-- Each bank-side card debit must ≈ that card's prior-month charge total (±1%).
-- Card mapping is description-based; extend the CASE when adding real cards.
with debits as (
    select
        posted_date,
        date_trunc('month', posted_date - interval 1 month) as statement_month,
        case
            when raw_description like '%מקס%'     then 'max-1234'
            when raw_description like '%ישראכרט%' then 'isracard-5678'
        end as card_account,
        abs(amount) as debit_ils
    from {{ ref('int_card_payments') }}
),

card_spend as (
    select
        account_id as card_account,
        posted_month as statement_month,
        sum(abs(amount)) as charges_ils
    from {{ ref('stg_transactions') }}
    where account_type = 'credit_card'
    group by 1, 2
)

select d.card_account, d.statement_month, d.debit_ils, c.charges_ils
from debits d
join card_spend c using (card_account, statement_month)
where abs(d.debit_ils - c.charges_ils) > c.charges_ils * 0.01
