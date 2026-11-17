-- First-attempt pass rate of the current passenger-car fleet by vehicle age.
select
    vehicle_age_years,
    fuel_group,
    count(*)                                                              as inspections,
    cast(round(avg(is_passed::integer), 4) as double)                     as first_pass_rate,
    cast(round(median(odometer_km)) as integer)                           as median_odometer_km
from {{ ref('int_inspections__recent_passenger_cars') }}
where vehicle_age_years between 0 and 30
  and fuel_group in ('Diesel', 'Petrol', 'LPG', 'Hybrid', 'Electric')
group by all
