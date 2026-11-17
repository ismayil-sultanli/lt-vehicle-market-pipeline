-- The current passenger-car fleet by make and model.
select
    make,
    model,
    count(*)                                                              as vehicles,
    cast(round(median(manufacture_year)) as integer)                      as median_manufacture_year,
    cast(round(median(vehicle_age_years), 1) as double)                   as median_age_years,
    cast(round(median(odometer_km)) as integer)                           as median_odometer_km,
    cast(round(avg(is_passed::integer), 4) as double)                     as first_pass_rate,
    cast(round(avg((fuel_group = 'Diesel')::integer), 4) as double)       as diesel_share
from {{ ref('int_inspections__recent_passenger_cars') }}
where make not in ('Other', 'Not disclosed') and model <> 'Unknown'
group by all
having count(*) >= {{ var('min_vehicles_per_model') }}
