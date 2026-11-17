-- One row per inspection: typed, renamed and de-duplicated.
--
-- The publisher released a large share of 2024 twice: identical rows under a
-- new record id. Rows are therefore identified by their full content, not by
-- the record id: two rows are the same inspection only if every published
-- attribute agrees. (Two genuinely separate visits that are identical in every
-- attribute within one week cannot be told apart from a re-publication and are
-- counted once; in the years without the publication fault this affects fewer
-- than 1 row in 2,000.)
{%- set identity = [
    'vehicle_id', 'inspection_week', 'station_id', 'inspection_type_lt',
    'conclusion_lt', 'is_passed', 'validity_months', 'odometer_km',
    'make_raw', 'model_raw', 'vehicle_class', 'body_type_code',
    'manufacture_year', 'fuel_lt', 'municipality_lt'
] %}

with source as (

    select * from {{ source('transeksta', 'apziura') }}

),

typed as (

    select
        _id                                             as record_id,
        try_cast(vda_id as bigint)                      as publisher_row_number,
        tp_id                                           as vehicle_id,
        ta_stoties_kodas                                as station_id,

        cast(ta_savaites_data as date)                  as inspection_week,

        {{ clean_text('tp_marke') }}                    as make_raw,
        {{ clean_text('tp_modelis') }}                  as model_raw,
        upper(trim(tp_klase))                           as vehicle_class,
        upper(trim(tp_kebulas))                         as body_type_code,
        try_cast(tp_pag_metai as integer)               as manufacture_year,
        lower(trim(tp_kuras))                           as fuel_lt,
        try_cast(tp_rida_km as bigint)                  as odometer_km,

        {{ clean_text('ta_stoties_savivaldybe') }}      as municipality_lt,
        {{ clean_text('ta_tipas') }}                    as inspection_type_lt,
        {{ clean_text('ta_isvada') }}                   as conclusion_lt,
        try_cast(ar_ta_islaikyta as boolean)            as is_passed,
        try_cast(ta_periodiskumas_men as integer)       as validity_months,

        _extracted_at                                   as extracted_at

    from source

),

deduplicated as (

    select *
    from typed
    qualify row_number() over (
        partition by {{ identity | join(', ') }}
        order by publisher_row_number, record_id
    ) = 1

)

select
    {{ surrogate_key(identity) }} as inspection_id,
    *
from deduplicated
