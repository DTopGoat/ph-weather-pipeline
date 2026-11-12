-- Gold: daily rollup per city (Asia/Manila calendar day).

with hourly as (
    select * from {{ ref('fct_weather_hourly') }}
),

daily as (
    select
        city_id,
        observed_date_local,
        count(*) as hours_observed,
        bool_and(is_forecast) as is_forecast_day,
        round(min(temperature_c), 1) as temp_min_c,
        round(max(temperature_c), 1) as temp_max_c,
        round(avg(temperature_c), 1) as temp_avg_c,
        round(max(heat_index_c), 1) as heat_index_max_c,
        round(sum(precipitation_mm), 1) as precipitation_total_mm,
        round(max(wind_speed_kmh), 1) as wind_max_kmh,
        round(avg(relative_humidity_pct), 0) as humidity_avg_pct,
        round(avg(pm2_5_ugm3), 1) as pm2_5_avg_ugm3,
        max(us_aqi) as us_aqi_max,
        -- most severe weather code of the day drives the daily icon
        max(weather_code) as weather_code_max
    from hourly
    group by city_id, observed_date_local
)

select
    d.*,
    wc.weather_description,
    ab.aqi_category as aqi_category_max,
    ab.aqi_color as aqi_color_max,
    hb.heat_category as heat_category_max
from daily as d
left join {{ ref('weather_codes') }} as wc
    on d.weather_code_max = wc.weather_code
left join {{ ref('aqi_bands') }} as ab
    on d.us_aqi_max >= ab.aqi_min and d.us_aqi_max < ab.aqi_max_exclusive
left join {{ ref('heat_index_bands') }} as hb
    on d.heat_index_max_c >= hb.heat_index_min_c and d.heat_index_max_c < hb.heat_index_max_exclusive_c
