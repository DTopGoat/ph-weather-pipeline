-- Gold: one row per city and hour, weather joined to air quality, with AQI and heat index bands.

with latest_load as (
    select max(loaded_at) as latest_loaded_at
    from {{ ref('stg_weather_hourly') }}
),

joined as (
    select
        w.city_id,
        w.observed_at_local,
        w.observed_at_utc,
        cast(w.observed_at_local as date) as observed_date_local,
        w.temperature_c,
        w.apparent_temperature_c,
        w.relative_humidity_pct,
        w.precipitation_mm,
        w.wind_speed_kmh,
        w.weather_code,
        a.pm2_5_ugm3,
        a.pm10_ugm3,
        a.us_aqi,
        {{ heat_index_c('w.temperature_c', 'w.relative_humidity_pct') }} as heat_index_c,
        w.observed_at_utc > l.latest_loaded_at as is_forecast,
        w.loaded_at
    from {{ ref('stg_weather_hourly') }} as w
    cross join latest_load as l
    left join {{ ref('stg_air_quality_hourly') }} as a
        on
            w.city_id = a.city_id
            and w.observed_at_local = a.observed_at_local
)

select
    j.city_id,
    j.observed_at_local,
    j.observed_at_utc,
    j.observed_date_local,
    j.is_forecast,
    j.temperature_c,
    j.apparent_temperature_c,
    j.relative_humidity_pct,
    j.precipitation_mm,
    j.wind_speed_kmh,
    j.weather_code,
    wc.weather_description,
    j.heat_index_c,
    hb.heat_category,
    hb.heat_band_order,
    j.pm2_5_ugm3,
    j.pm10_ugm3,
    j.us_aqi,
    ab.aqi_category,
    ab.aqi_band_order,
    ab.aqi_color,
    j.loaded_at
from joined as j
left join {{ ref('weather_codes') }} as wc
    on j.weather_code = wc.weather_code
left join {{ ref('aqi_bands') }} as ab
    on j.us_aqi >= ab.aqi_min and j.us_aqi < ab.aqi_max_exclusive
left join {{ ref('heat_index_bands') }} as hb
    on j.heat_index_c >= hb.heat_index_min_c and j.heat_index_c < hb.heat_index_max_exclusive_c
