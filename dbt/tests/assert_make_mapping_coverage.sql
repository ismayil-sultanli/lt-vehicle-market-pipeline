-- The make alias seed must resolve at least 98% of passenger-car inspections.
-- A failure means a new spelling became common and belongs in vehicle_makes.csv.
with coverage as (
    select
        count(*)                                 as inspections,
        count(*) filter (where make = 'Other')   as unmapped
    from {{ ref('fct_inspections') }}
    where is_passenger_car
)

select * from coverage where unmapped > 0.02 * inspections
