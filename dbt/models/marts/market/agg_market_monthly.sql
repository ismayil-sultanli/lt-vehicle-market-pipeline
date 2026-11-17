-- Monthly market overview for arm's-length sales, split by vehicle origin.
with sales as (

    select * from {{ ref('fct_vehicle_transactions') }}
    where is_market_sale

),

last_month as (

    select
        cast(
            date_trunc('month', max(transaction_date))
            - interval '{{ var("settling_months") }} months' as date
        ) as last_settled_month
    from sales

)

select
    transaction_month,
    case when is_import then 'Imported' else 'Domestic' end           as origin_type,

    count(*)                                                          as transactions,
    count(*) filter (where has_valid_price)                           as priced_transactions,

    cast(round(median(amount_eur) filter (where has_valid_price), 0) as integer)       as median_price_eur,
    cast(round(quantile_cont(amount_eur, 0.25) filter (where has_valid_price), 0) as integer) as p25_price_eur,
    cast(round(quantile_cont(amount_eur, 0.75) filter (where has_valid_price), 0) as integer) as p75_price_eur,
    cast(round(avg(amount_eur) filter (where has_valid_price), 0) as integer)          as mean_price_eur,
    cast(round(sum(amount_eur) filter (where has_valid_price), 0) as bigint)          as declared_value_eur,

    -- Trend charts should only plot settled months: not the months before the
    -- dataset's coverage starts, and not the newest ones, which are still
    -- receiving late registrations.
    transaction_month >= date '{{ var("coverage_start_date") }}'
    and transaction_month <= (select last_settled_month from last_month) as is_complete_month

from sales
group by all
