-- Per category x month: actual vs budget, prorated pace for the current month.
-- pace_ils convention: positive = under budget (good), negative = over.
-- Every budgeted category appears in every month EVEN WITH ZERO SPEND, so the
-- dashboard always shows the full budget picture ("we spent nothing on X yet").
with spend as (
    select posted_month, category_id, sum(spend_ils) as actual_ils
    from {{ ref('fct_spend') }}
    group by 1, 2
),

months as (
    select distinct posted_month from spend
),

budgets as (
    select category_id, monthly_amount_ils from {{ source('state', 'budgets') }}
),

scaffold as (
    select m.posted_month, b.category_id
    from months m
    cross join budgets b
    union
    select posted_month, category_id from spend
),

calendar as (
    select
        posted_month,
        case
            when posted_month = date_trunc('month', current_date)
            then extract(day from current_date)::double
                 / extract(day from (date_trunc('month', current_date)
                     + interval 1 month - interval 1 day))::double
            else 1.0
        end as month_fraction
    from months
)

select
    sc.posted_month,
    sc.category_id,
    coalesce(s.actual_ils, 0)                                            as actual_ils,
    b.monthly_amount_ils                                                 as budget_ils,
    round(coalesce(b.monthly_amount_ils, 0) * c.month_fraction, 2)       as budget_to_date_ils,
    round(coalesce(b.monthly_amount_ils, 0) * c.month_fraction
          - coalesce(s.actual_ils, 0), 2)                                as pace_ils,
    case
        when b.monthly_amount_ils is null then 'no_budget'
        when coalesce(s.actual_ils, 0) <= b.monthly_amount_ils * c.month_fraction then 'under'
        else 'over'
    end as pace_status
from scaffold sc
left join spend s using (posted_month, category_id)
left join budgets b using (category_id)
join calendar c using (posted_month)
