-- The household's category list: the built-in set from the dbt seed, plus any the
-- owner added from the dashboard (state.categories, which dbt only reads).
-- is_custom drives the UI: only owner-added categories can be deleted, because the
-- seed ones are dbt-managed and 'other'/'income' are relied on by the SQL itself.
select
    category_id,
    name_he,
    name_en,
    false as is_custom
from {{ ref('dim_category_seed') }}

union all

select
    category_id,
    name_he,
    name_he as name_en,
    true as is_custom
from {{ source('state', 'categories') }}
-- an id that already exists in the seed must not produce a second row, or the
-- unique test on category_id fails and every join downstream doubles up
where category_id not in (select category_id from {{ ref('dim_category_seed') }})
