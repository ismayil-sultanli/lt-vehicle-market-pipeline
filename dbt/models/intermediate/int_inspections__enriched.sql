-- Inspections with English categories, a normalised make and model, and
-- validated numeric attributes.
with inspections as (

    select
        *,
        {{ normalise_make('make_raw') }} as make_key
    from {{ ref('stg_transeksta__inspections') }}

),

makes        as (select * from {{ ref('vehicle_makes') }}),
classes      as (select * from {{ ref('vehicle_classes') }}),
fuels        as (select * from {{ ref('fuel_types') }}),
types        as (select * from {{ ref('inspection_types') }}),
conclusions  as (select * from {{ ref('inspection_conclusions') }}),

joined as (

    select
        i.inspection_id,
        i.vehicle_id,
        i.station_id,
        i.inspection_week,
        cast(extract(year from i.inspection_week) as integer)    as inspection_year,

        i.municipality_lt                                        as municipality,

        coalesce(t.inspection_type, 'Unmapped')                  as inspection_type,
        coalesce(t.is_first_attempt, false)                      as is_first_attempt,
        coalesce(c.conclusion, 'Unmapped')                       as conclusion,
        i.is_passed,
        i.validity_months,

        i.make_raw,
        i.make_key,
        coalesce(m.make, 'Other')                                as make,
        upper(i.model_raw)                                       as model_upper,
        i.vehicle_class,
        coalesce(k.vehicle_class_name, 'Other')                  as vehicle_class_name,
        coalesce(k.vehicle_category, 'Other')                    as vehicle_category,
        i.body_type_code,

        coalesce(f.fuel_type, 'Not recorded')                    as fuel_type,
        coalesce(f.fuel_group, 'Not recorded')                   as fuel_group,

        i.manufacture_year,
        i.odometer_km                                            as odometer_km_raw,
        i.extracted_at

    from inspections as i
    left join makes       as m on i.make_key = m.make_key
    left join classes     as k on i.vehicle_class = k.vehicle_class
    left join fuels       as f on i.fuel_lt = f.fuel_lt
    left join types       as t on i.inspection_type_lt = t.inspection_type_lt
    left join conclusions as c on i.conclusion_lt = c.conclusion_lt

),

final as (

    select
        * exclude (model_upper, odometer_km_raw),

        -- Stations often repeat the make inside the model field ("AUDI A6").
        case
            when model_upper is null then 'Unknown'
            when starts_with(model_upper, make_key || ' ')
                then trim(substr(model_upper, length(make_key) + 2))
            when starts_with(model_upper, upper(make) || ' ')
                then trim(substr(model_upper, length(make) + 2))
            else model_upper
        end                                                      as model,

        -- plausible vehicle age only; a typo in the year must not skew medians
        case
            when manufacture_year between 1950 and inspection_year
                then inspection_year - manufacture_year
        end                                                      as vehicle_age_years,

        -- zero and absurd readings are data-entry noise, not mileage
        case
            when odometer_km_raw between 1 and {{ var('max_valid_odometer_km') }}
                then odometer_km_raw
        end                                                      as odometer_km,

        vehicle_category = 'Passenger cars'                      as is_passenger_car

    from joined

)

select * from final
