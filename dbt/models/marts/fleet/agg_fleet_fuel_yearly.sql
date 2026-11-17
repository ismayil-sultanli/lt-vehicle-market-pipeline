-- Fuel mix of passenger cars presented for periodic inspection, per year.
with cars as (

    select * from {{ ref('fct_inspections') }}
    where is_passenger_car and is_first_attempt

),

last_year as (

    select max(inspection_year) as newest_year, max(inspection_week) as last_week from cars

),

counted as (

    select
        inspection_year,
        fuel_group,
        count(distinct vehicle_id)                                        as vehicles,
        cast(round(median(vehicle_age_years), 1) as double)               as median_age_years,
        cast(round(avg(is_passed::integer), 4) as double)                 as first_pass_rate
    from cars
    group by all

)

select
    c.*,
    cast(
        round(c.vehicles / sum(c.vehicles) over (partition by c.inspection_year), 4) as double
    )                                                                     as share_of_year,
    -- the newest year only counts if the data runs to its last week
    c.inspection_year < l.newest_year or l.last_week >= make_date(l.newest_year, 12, 24)
                                                                          as is_complete_year
from counted as c
cross join last_year as l
