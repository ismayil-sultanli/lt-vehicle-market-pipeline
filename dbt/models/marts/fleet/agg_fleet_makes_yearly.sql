-- Passenger cars per make and year: fleet size, age, mileage and pass rate.
select
    inspection_year,
    make,
    count(distinct vehicle_id)                                            as vehicles,
    cast(round(median(vehicle_age_years), 1) as double)                   as median_age_years,
    cast(round(median(odometer_km)) as integer)                           as median_odometer_km,
    cast(round(avg(is_passed::integer), 4) as double)                     as first_pass_rate
from {{ ref('fct_inspections') }}
where is_passenger_car and is_first_attempt
group by all
