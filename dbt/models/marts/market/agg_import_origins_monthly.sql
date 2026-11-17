-- Where imported vehicles come from, and what buyers declare paying for them.
select
    transaction_month,
    origin_country,
    origin_country_code,
    origin_region,
    count(*)                                                     as transactions,
    count(*) filter (where has_valid_price)                      as priced_transactions,
    cast(round(median(amount_eur) filter (where has_valid_price), 0) as integer)  as median_price_eur
from {{ ref('fct_vehicle_transactions') }}
where is_market_sale and is_import
group by all
