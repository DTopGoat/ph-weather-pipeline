select
    city_id,
    city_name,
    region,
    island_group,
    latitude,
    longitude
from {{ ref('cities') }}
