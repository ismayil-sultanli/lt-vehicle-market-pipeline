-- How vehicles are paid for, above and below the statutory cash limit.
-- Supports the question: did the 2022 cash restriction change behaviour?
with sales as (

    select * from {{ ref('fct_vehicle_transactions') }}
    where is_market_sale and has_valid_price

),

counted as (

    select
        transaction_month,
        case
            when is_above_cash_limit then 'Above cash limit'
            else 'At or below cash limit'
        end                                    as price_segment,
        payment_method,
        count(*)                               as transactions
    from sales
    group by all

)

select
    *,
    cast(round(
        transactions / sum(transactions) over (partition by transaction_month, price_segment),
        4
    ) as double)                               as share_of_segment,
    transaction_month >= date '{{ var("cash_limit_effective_date") }}' as is_after_cash_limit_law
from counted
