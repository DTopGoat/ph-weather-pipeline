{#
  Heat index in degrees Celsius from air temperature (C) and relative humidity (%),
  using the NOAA/NWS Rothfusz regression with Steadman's simple formula below 80 F.
  PAGASA publishes its heat index warnings using the same concept.
#}
{% macro heat_index_c(temp_c, rh) -%}
    case
        when {{ temp_c }} is null or {{ rh }} is null then null
        else round(((
            case
                when 0.5 * (({{ temp_c }} * 1.8 + 32) + 61 + (({{ temp_c }} * 1.8 + 32) - 68) * 1.2 + {{ rh }} * 0.094) < 80
                    then 0.5 * (({{ temp_c }} * 1.8 + 32) + 61 + (({{ temp_c }} * 1.8 + 32) - 68) * 1.2 + {{ rh }} * 0.094)
                else -42.379
                    + 2.04901523 * ({{ temp_c }} * 1.8 + 32)
                    + 10.14333127 * {{ rh }}
                    - 0.22475541 * ({{ temp_c }} * 1.8 + 32) * {{ rh }}
                    - 0.00683783 * ({{ temp_c }} * 1.8 + 32) * ({{ temp_c }} * 1.8 + 32)
                    - 0.05481717 * {{ rh }} * {{ rh }}
                    + 0.00122874 * ({{ temp_c }} * 1.8 + 32) * ({{ temp_c }} * 1.8 + 32) * {{ rh }}
                    + 0.00085282 * ({{ temp_c }} * 1.8 + 32) * {{ rh }} * {{ rh }}
                    - 0.00000199 * ({{ temp_c }} * 1.8 + 32) * ({{ temp_c }} * 1.8 + 32) * {{ rh }} * {{ rh }}
            end
        ) - 32) / 1.8, 1)
    end
{%- endmacro %}
