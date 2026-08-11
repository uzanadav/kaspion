select category_id, name_he, name_en
from {{ ref('dim_category_seed') }}
