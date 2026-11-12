{{
    config(
        materialized='incremental',
        unique_key=['city_id', 'observed_at_local'],
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

-- Silver: typed, deduplicated air quality. Same latest-record-per-key logic as weather.

with source_rows as (
    select src.*
    from {{ source('bronze', 'raw_air_quality_hourly') }} as src
    {% if is_incremental() %}
        where src.loaded_at >= (
            select max(silver_rows.loaded_at) - interval ({{ var('lookback_hours') }}) hour
            from {{ this }} as silver_rows
        )
    {% endif %}
),

typed as (
    select
        city_id,
        strptime(local_time, '%Y-%m-%dT%H:%M') as observed_at_local,
        cast(pm2_5 as double) as pm2_5_ugm3,
        cast(pm10 as double) as pm10_ugm3,
        cast(us_aqi as integer) as us_aqi,
        loaded_at,
        run_id
    from source_rows
),

ranked as (
    select
        *,
        row_number() over (
            partition by city_id, observed_at_local
            order by loaded_at desc, run_id desc
        ) as load_rank
    from typed
)

select
    city_id,
    observed_at_local,
    pm2_5_ugm3,
    pm10_ugm3,
    us_aqi,
    loaded_at,
    run_id
from ranked
where load_rank = 1
