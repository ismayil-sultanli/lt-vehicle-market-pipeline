-- Consecutive periodic inspections of the same passenger car, paired up to
-- measure distance driven per year and to spot readings that went backwards.
with readings as (

    select
        vehicle_id,
        inspection_id,
        inspection_week,
        inspection_year,
        fuel_group,
        vehicle_age_years,
        odometer_km
    from {{ ref('int_inspections__enriched') }}
    where is_passenger_car
      and is_first_attempt
      and odometer_km is not null

),

paired as (

    select
        *,
        lag(odometer_km)     over vehicle_history as previous_odometer_km,
        lag(inspection_week) over vehicle_history as previous_inspection_week
    from readings
    window vehicle_history as (partition by vehicle_id order by inspection_week, inspection_id)

),

intervals as (

    select
        vehicle_id,
        inspection_id,
        inspection_week,
        inspection_year,
        fuel_group,
        vehicle_age_years,
        previous_inspection_week,
        previous_odometer_km,
        odometer_km,
        odometer_km - previous_odometer_km                           as distance_km,
        date_diff('day', previous_inspection_week, inspection_week)  as days_between
    from paired
    where previous_inspection_week is not null

)

select
    *,
    distance_km < 0                                                  as is_lower_reading,
    distance_km <= -{{ var('odometer_rollback_threshold_km') }}      as is_suspected_rollback,
    -- only intervals of roughly a year or more give a stable yearly figure
    case
        when days_between >= 300 and distance_km >= 0
            then cast(round(distance_km * 365.25 / days_between) as integer)
    end                                                              as annual_km
from intervals
-- a second periodic inspection in the same week is a duplicate visit, not an interval
where days_between > 0
