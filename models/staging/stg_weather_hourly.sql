{{
    config(
        materialized='incremental',
        unique_key=['city_id', 'observed_at_local'],
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

-- Silver: typed, deduplicated weather. One row per city and hour, keeping the most
-- recently loaded value (later runs refine forecasts and fill in recent hours).

with source_rows as (
    select src.*
    from {{ source('bronze', 'raw_weather_hourly') }} as src
    {% if is_incremental() %}
        -- Watermark with a lookback window: reprocess anything loaded within
        -- `lookback_hours` of the newest row already in Silver.
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
        strptime(local_time, '%Y-%m-%dT%H:%M') - interval 8 hour as observed_at_utc,
        cast(temperature_2m as double) as temperature_c,
        cast(apparent_temperature as double) as apparent_temperature_c,
        cast(relative_humidity_2m as double) as relative_humidity_pct,
        cast(precipitation as double) as precipitation_mm,
        cast(wind_speed_10m as double) as wind_speed_kmh,
        cast(weather_code as integer) as weather_code,
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
    observed_at_utc,
    temperature_c,
    apparent_temperature_c,
    relative_humidity_pct,
    precipitation_mm,
    wind_speed_kmh,
    weather_code,
    loaded_at,
    run_id
from ranked
where load_rank = 1
