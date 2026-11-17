-- Single-row summary of the inspection subject area, including how many
-- duplicate rows the staging model removed.
with raw as (

    select count(*) as published_rows
    from {{ source('transeksta', 'apziura') }}

),

clean as (

    select
        count(*)                    as inspections,
        count(distinct vehicle_id)  as vehicles,
        min(inspection_week)        as first_inspection_week,
        max(inspection_week)        as last_inspection_week
    from {{ ref('fct_inspections') }}

),

fleet as (

    select
        count(*)                                                          as current_passenger_cars,
        cast(round(median(vehicle_age_years), 1) as double)               as median_age_years,
        cast(round(avg(is_passed::integer), 4) as double)                 as first_pass_rate,
        cast(round(avg((fuel_group = 'Diesel')::integer), 4) as double)   as diesel_share,
        min(inspection_week)                                              as window_start_week
    from {{ ref('int_inspections__recent_passenger_cars') }}

)

select
    raw.published_rows,
    clean.inspections,
    raw.published_rows - clean.inspections                                as duplicate_rows_removed,
    clean.vehicles,
    clean.first_inspection_week,
    clean.last_inspection_week,
    fleet.current_passenger_cars,
    fleet.median_age_years,
    fleet.first_pass_rate,
    fleet.diesel_share,
    fleet.window_start_week,
    cast(current_timestamp as timestamp)                                  as built_at
from raw
cross join clean
cross join fleet
