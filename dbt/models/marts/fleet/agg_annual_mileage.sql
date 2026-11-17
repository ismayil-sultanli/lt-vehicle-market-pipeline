-- Distance driven per year, from consecutive inspections of the same car.
with intervals as (

    select
        *,
        case
            when vehicle_age_years < 5  then '0-4 years'
            when vehicle_age_years < 10 then '5-9 years'
            when vehicle_age_years < 15 then '10-14 years'
            when vehicle_age_years < 20 then '15-19 years'
            else '20+ years'
        end as age_band,
        case
            when vehicle_age_years < 5  then 1
            when vehicle_age_years < 10 then 2
            when vehicle_age_years < 15 then 3
            when vehicle_age_years < 20 then 4
            else 5
        end as age_band_order
    from {{ ref('int_inspections__odometer_intervals') }}
    where annual_km is not null
      and vehicle_age_years is not null
      -- above 150,000 km a year is a taxi fleet at best and a typo at worst
      and annual_km <= 150000

)

select
    fuel_group,
    age_band,
    age_band_order,
    count(*)                                                              as intervals,
    cast(round(median(annual_km)) as integer)                             as median_annual_km,
    cast(round(quantile_cont(annual_km, 0.25)) as integer)                as p25_annual_km,
    cast(round(quantile_cont(annual_km, 0.75)) as integer)                as p75_annual_km
from intervals
where fuel_group in ('Diesel', 'Petrol', 'LPG', 'Hybrid', 'Electric')
group by all
