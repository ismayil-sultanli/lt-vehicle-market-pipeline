-- One row per vehicle, described by its most recent inspection.
with ranked as (

    select
        *,
        row_number() over (
            partition by vehicle_id
            order by inspection_week desc, inspection_id desc
        ) as recency
    from {{ ref('fct_inspections') }}

),

history as (

    select
        vehicle_id,
        min(inspection_week) as first_inspection_week,
        max(inspection_week) as last_inspection_week,
        count(*)             as inspections,
        max(odometer_km)     as highest_odometer_km
    from {{ ref('fct_inspections') }}
    group by vehicle_id

)

select
    r.vehicle_id,
    r.make,
    r.model,
    r.vehicle_class,
    r.vehicle_class_name,
    r.vehicle_category,
    r.is_passenger_car,
    r.fuel_type,
    r.fuel_group,
    r.manufacture_year,
    r.municipality                 as last_municipality,
    r.odometer_km                  as last_odometer_km,
    h.highest_odometer_km,
    h.first_inspection_week,
    h.last_inspection_week,
    h.inspections
from ranked as r
inner join history as h on r.vehicle_id = h.vehicle_id
where r.recency = 1
