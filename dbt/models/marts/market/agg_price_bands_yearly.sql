-- Distribution of declared sale prices per year.
with sales as (

    select * from {{ ref('fct_vehicle_transactions') }}
    where is_market_sale and currency_code = 'EUR'

),

counted as (

    select
        cast(extract(year from transaction_date) as integer)  as transaction_year,
        price_band,
        price_band_order                                      as band_order,
        count(*)                                              as transactions
    from sales
    group by all

)

select
    *,
    cast(
        round(transactions / sum(transactions) over (partition by transaction_year), 4) as double
    )                                                         as share_of_year
from counted
