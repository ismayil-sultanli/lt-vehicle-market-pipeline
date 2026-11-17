-- Translate categorical values through the reference seeds and derive the
-- business flags every mart relies on.
with transactions as (

    select * from {{ ref('stg_regitra__transactions') }}

),

document_types as (select * from {{ ref('document_types') }}),
countries      as (select * from {{ ref('countries') }}),
currencies     as (select * from {{ ref('currencies') }}),
payment_methods as (select * from {{ ref('payment_methods') }}),

joined as (

    select
        t.transaction_id,
        t.document_id,
        t.registry_operation_id,
        t.transaction_date,
        cast(date_trunc('month', t.transaction_date) as date)   as transaction_month,
        t.modified_at,
        t.extracted_at,

        coalesce(d.document_type_en, 'Unmapped')                as document_type,
        coalesce(d.transaction_category, 'other')               as transaction_category,
        coalesce(d.is_market_sale, false)                       as is_market_sale,

        -- rare / mis-keyed countries outside the reference seed collapse to "Other"
        case
            when t.country_lt is null then 'Not specified'
            else coalesce(c.country_en, 'Other')
        end                                                     as origin_country,
        c.iso2                                                  as origin_country_code,
        case
            when t.country_lt is null then 'Unknown'
            else coalesce(c.region, 'Other')
        end                                                     as origin_region,
        coalesce(
            t.country_lt is not null
            and coalesce(c.country_en, 'Other') not in ('Lithuania', 'Not specified'),
            false
        )                                                       as is_import,

        coalesce(p.payment_method, 'Not specified')             as payment_method,
        coalesce(cur.currency_code, 'OTHER')                    as currency_code,
        t.declared_amount

    from transactions as t
    left join document_types  as d   on t.document_type_lt = d.document_type_lt
    left join countries       as c   on t.country_lt = c.country_lt
    left join currencies      as cur on t.currency_lt = cur.currency_lt
    left join payment_methods as p   on t.payment_method_lt = p.payment_method_lt

),

final as (

    select
        *,
        -- No FX conversion: ~98% of documents are in EUR; the rest are kept as
        -- transactions but excluded from price statistics.
        case when currency_code = 'EUR' then declared_amount end as amount_eur,

        coalesce(
            currency_code = 'EUR'
            and declared_amount between {{ var('min_valid_price_eur') }}
                                    and {{ var('max_valid_price_eur') }},
            false
        )                                                        as has_valid_price,

        {%- set bands = [
            (100, 'Under 100'), (1000, '100 - 999'), (2500, '1,000 - 2,499'),
            (5000, '2,500 - 4,999'), (10000, '5,000 - 9,999'),
            (20000, '10,000 - 19,999'), (40000, '20,000 - 39,999'),
        ] %}

        case
            when currency_code <> 'EUR' then 'Non-EUR'
            {%- for upper, label in bands %}
            when declared_amount < {{ upper }} then '{{ label }}'
            {%- endfor %}
            else '40,000 and above'
        end                                                      as price_band,

        -- sort key so charts can order the bands from low to high
        case
            when currency_code <> 'EUR' then 0
            {%- for upper, label in bands %}
            when declared_amount < {{ upper }} then {{ loop.index }}
            {%- endfor %}
            else {{ bands | length + 1 }}
        end                                                      as price_band_order,

        coalesce(
            currency_code = 'EUR' and declared_amount > {{ var('cash_limit_eur') }}, false
        )                                                        as is_above_cash_limit,
        transaction_date >= date '{{ var("cash_limit_effective_date") }}'
                                                                 as is_after_cash_limit_law

    from joined

)

select * from final
