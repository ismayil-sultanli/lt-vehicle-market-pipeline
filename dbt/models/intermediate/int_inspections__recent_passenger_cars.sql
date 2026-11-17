-- First-attempt periodic inspections of passenger cars within the "current
-- fleet" window: the last N months of data, in which each active car shows up
-- about once. One row per vehicle (its latest inspection in the window).
with bounds as (

    select max(inspection_week) as last_week
    from {{ ref('fct_inspections') }}

),

in_window as (

    select f.*
    from {{ ref('fct_inspections') }} as f
    cross join bounds as b
    where f.is_passenger_car
      and f.is_first_attempt
      and f.inspection_week > b.last_week - interval '{{ var("fleet_window_months") }} months'

)

select *
from in_window
qualify row_number() over (
    partition by vehicle_id
    order by inspection_week desc, inspection_id desc
) = 1
