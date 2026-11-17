-- One row per transaction document: latest version only, typed and renamed.
with source as (

    select * from {{ source('regitra', 'sandoris') }}

),

latest_version as (

    -- A document edited after its first load exists in several monthly
    -- partitions; keep the most recently modified version.
    select *
    from source
    qualify row_number() over (
        partition by _id
        order by cast(iraso_mod_data as timestamp) desc, _extracted_at desc
    ) = 1

),

renamed as (

    select
        _id                                            as transaction_id,
        dok_id                                         as document_id,
        veiklos_id                                     as registry_operation_id,

        cast(cast(isd_data as timestamp) as date)      as transaction_date,
        cast(iraso_mod_data as timestamp)              as modified_at,

        {{ clean_text('dok_rusis') }}                  as document_type_lt,
        {{ clean_text('salis') }}                      as country_lt,
        {{ clean_text('valiuta') }}                    as currency_lt,
        {{ clean_text('mokejimo_budas') }}             as payment_method_lt,

        try_cast(suma as decimal(16, 2))               as declared_amount,

        _extracted_at                                  as extracted_at

    from latest_version

)

select * from renamed
