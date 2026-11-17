-- Sales declared within EUR 100 of the cash limit, per month.
-- If the limit shapes what people write on the contract, declarations pile up
-- just below it once the law is in force.
{%- set limit = var('cash_limit_eur') %}

with sales as (

    select * from {{ ref('fct_vehicle_transactions') }}
    where is_market_sale
      and currency_code = 'EUR'
      and amount_eur between {{ limit - 100 }} and {{ limit + 100 }}

)

select
    transaction_month,
    case
        when amount_eur < {{ limit }} then 'Just below the limit'
        when amount_eur = {{ limit }} then 'Exactly at the limit'
        else 'Just above the limit'
    end                                                    as price_position,
    count(*)                                               as transactions,
    count(*) filter (where payment_method = 'Cash')        as cash_transactions,
    transaction_month >= date '{{ var("cash_limit_effective_date") }}' as is_after_cash_limit_law
from sales
group by all
