-- Inter-account transfers: opposite sign, same abs amount (±1 ILS), within 3 days,
-- between the owner's own BANK accounts. Card payments are handled separately
-- (int_card_payments) because the Israeli monthly חיוב is not a pair-match.
with bank_txns as (
    select * from {{ ref('stg_transactions') }}
    where account_type = 'bank'
),

pairs as (
    select
        o.transaction_id as out_id,
        i.transaction_id as in_id,
        row_number() over (
            partition by o.transaction_id
            order by abs(datediff('day', o.posted_date, i.posted_date)), i.transaction_id
        ) as rn_out,
        row_number() over (
            partition by i.transaction_id
            order by abs(datediff('day', o.posted_date, i.posted_date)), o.transaction_id
        ) as rn_in
    from bank_txns o
    join bank_txns i
      on o.amount < 0
     and i.amount > 0
     and abs(o.amount + i.amount) <= 1.0
     and o.account_id <> i.account_id
     and abs(datediff('day', o.posted_date, i.posted_date)) <= 3
),

matched as (
    select out_id, in_id from pairs where rn_out = 1 and rn_in = 1
)

select out_id as transaction_id, in_id as counterpart_id from matched
union all
select in_id as transaction_id, out_id as counterpart_id from matched
