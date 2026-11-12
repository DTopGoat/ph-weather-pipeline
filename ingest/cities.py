"""Cities tracked by the pipeline. Keep in sync with dbt/seeds/cities.csv."""

CITIES = [
    {"city_id": "baguio", "city_name": "Baguio", "region": "CAR", "latitude": 16.4023, "longitude": 120.5960},
    {"city_id": "quezon_city", "city_name": "Quezon City (Metro Manila)", "region": "NCR",
     "latitude": 14.6760, "longitude": 121.0437},
    {"city_id": "cebu", "city_name": "Cebu City", "region": "Central Visayas", "latitude": 10.3157, "longitude": 123.8854},
    {"city_id": "davao", "city_name": "Davao City", "region": "Davao Region", "latitude": 7.1907, "longitude": 125.4553},
    {"city_id": "iloilo", "city_name": "Iloilo City", "region": "Western Visayas", "latitude": 10.7202, "longitude": 122.5621},
    {"city_id": "cagayan_de_oro", "city_name": "Cagayan de Oro", "region": "Northern Mindanao",
     "latitude": 8.4542, "longitude": 124.6319},
]
