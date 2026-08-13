-- Per category x month: actual vs the full monthly budget.
-- pace_ils convention: positive = under budget (good), negative = over.
-- Deliberately NOT prorated by day-of-month: a lump-sum category paid in full early
-- (rent, insurance) would otherwise show "over" for most of every month regardless
-- of the budget set, since day-13-of-31 spend always looks huge against a 13/31
-- slice of the budget. Comparing to the full month keeps the signal meaningful for
-- both lump-sum and day-by-day categories alike.
-- Budget = the owner's explicit state.budgets value if set, else a smart default:
-- the trailing 3-COMPLETED-month average spend for that category (rounded to the
-- nearest ₪50, current month excluded since it's still partial and would skew low).
-- The owner's own number always wins and is never overwritten by the average —
-- this only fills in a sensible starting point before they've set one themselves.
-- Every category appears in every month EVEN WITH ZERO SPEND, so the dashboard
-- always shows the full budget picture ("we spent nothing on X yet").
with spend as (
    select posted_month, category_id, sum(spend_ils) as actual_ils
    from {{ ref('fct_spend') }}
    group by 1, 2
),

months as (
    select distinct posted_month from spend
),

categories as (
    select category_id from {{ ref('dim_category') }} where category_id != 'income'
),

budgets as (
    select category_id, monthly_amount_ils from {{ source('state', 'budgets') }}
),

-- The window the suggestion averages over: the completed months in the last three,
-- as CALENDAR months rather than "the last three months this category happened to
-- spend in". Averaging only spending months turns a ₪3,000 annual insurance premium
-- into a ₪3,000 monthly budget, and without a lower bound a category last used two
-- years ago would still get a live suggestion for this month.
recent_window as (
    select distinct posted_month
    from spend
    where posted_month < date_trunc('month', current_date)
      and posted_month >= date_trunc('month', current_date) - interval 3 month
),

suggested as (
    select
        c.category_id,
        -- months inside the window with no spend count as zero, so the divisor is the
        -- window size, not the number of months that happened to have a charge
        greatest(
            round(sum(coalesce(s.actual_ils, 0))
                  / greatest(count(*), 1) / 50) * 50, 50) as suggested_ils
    from categories c
    cross join recent_window w
    left join spend s on s.category_id = c.category_id and s.posted_month = w.posted_month
    group by 1
    having sum(coalesce(s.actual_ils, 0)) > 0
),

scaffold as (
    select m.posted_month, c.category_id
    from months m
    cross join categories c
),

resolved as (
    select
        sc.posted_month,
        sc.category_id,
        coalesce(s.actual_ils, 0)                          as actual_ils,
        coalesce(b.monthly_amount_ils, sg.suggested_ils)   as budget_ils,
        b.monthly_amount_ils is null
            and sg.suggested_ils is not null                as budget_is_suggested
    from scaffold sc
    left join spend s using (posted_month, category_id)
    left join budgets b using (category_id)
    left join suggested sg using (category_id)
)

select
    posted_month,
    category_id,
    actual_ils,
    budget_ils,
    budget_is_suggested,
    round(coalesce(budget_ils, 0), 2)               as budget_to_date_ils,
    round(coalesce(budget_ils, 0) - actual_ils, 2)  as pace_ils,
    case
        when budget_ils is null then 'no_budget'
        when actual_ils <= budget_ils then 'under'
        else 'over'
    end as pace_status
from resolved
