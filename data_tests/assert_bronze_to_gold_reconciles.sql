-- Row-count reconciliation across layers. Every distinct (city, hour) key that exists in
-- Bronze must appear exactly once in Silver and once in Gold, and Gold must not invent keys.
-- Returns one row per failing check.

with bronze_keys as (
    select count(distinct city_id || '|' || local_time) as n
    from {{ source('bronze', 'raw_weather_hourly') }}
),

silver_in_bronze as (
    select count(*) as n
    from {{ ref('stg_weather_hourly') }} as s
    where exists (
        select 1
        from {{ source('bronze', 'raw_weather_hourly') }} as b
        where
            b.city_id = s.city_id
            and strptime(b.local_time, '%Y-%m-%dT%H:%M') = s.observed_at_local
    )
),

silver_total as (
    select count(*) as n from {{ ref('stg_weather_hourly') }}
),

gold_total as (
    select count(*) as n from {{ ref('fct_weather_hourly') }}
),

checks as (
    select
        'bronze_keys_vs_silver' as check_name,
        b.n as expected,
        s.n as actual
    from bronze_keys as b cross join silver_in_bronze as s
    union all
    select
        'silver_vs_gold' as check_name,
        s.n as expected,
        g.n as actual
    from silver_total as s cross join gold_total as g
)

select
    check_name,
    expected,
    actual
from checks
where expected != actual
