-- Resolution order: owner override ALWAYS wins > AI proposal > default.
with txns as (
    select * from {{ ref('stg_transactions') }}
),

overrides as (
    select merchant_key, category_id from {{ source('state', 'merchant_overrides') }}
),

proposals as (
    select merchant_key, proposed_category_id from {{ source('state', 'ai_proposals') }}
)

select
    t.*,
    coalesce(
        o.category_id,
        p.proposed_category_id,
        case when t.amount > 0 then 'income' else 'other' end
    ) as category_id,
    case
        when o.category_id is not null then 'override'
        when p.proposed_category_id is not null then 'ai'
        else 'default'
    end as category_source,
    tr.transaction_id is not null  as is_transfer,
    cp.transaction_id is not null  as is_card_payment,
    rf.transaction_id is not null  as is_refunded,
    -- which half of the pair this row is, so the UI can say "הוחזר" on the charge and
    -- "החזר" on the credit rather than the same word twice
    coalesce(rf.is_charge_leg, false) as is_refund_charge
from txns t
left join overrides o  on t.merchant_key = o.merchant_key
left join proposals p  on t.merchant_key = p.merchant_key
left join {{ ref('int_transfers_detected') }} tr on t.transaction_id = tr.transaction_id
left join {{ ref('int_card_payments') }}     cp on t.transaction_id = cp.transaction_id
left join {{ ref('int_refunds_detected') }} rf on t.transaction_id = rf.transaction_id
