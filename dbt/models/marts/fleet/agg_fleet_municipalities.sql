-- The current passenger-car fleet by municipality of the inspection station.
select
    municipality,
    count(*)                                                              as vehicles,
    cast(round(median(vehicle_age_years), 1) as double)                   as median_age_years,
    cast(round(median(odometer_km)) as integer)                           as median_odometer_km,
    cast(round(avg(is_passed::integer), 4) as double)                     as first_pass_rate,
    cast(round(avg((fuel_group = 'Diesel')::integer), 4) as double)       as diesel_share,
    cast(
        round(avg((fuel_group in ('Electric', 'Hybrid'))::integer), 4) as double
    )                                                                     as electrified_share
from {{ ref('int_inspections__recent_passenger_cars') }}
where municipality is not null
group by all
