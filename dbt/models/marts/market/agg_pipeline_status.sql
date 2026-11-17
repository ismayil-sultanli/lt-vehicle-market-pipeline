-- Single-row health summary shown in the dashboard footer.
select
    count(*)                                   as documents,
    count(*) filter (where is_market_sale)     as market_sales,
    min(transaction_date)                      as first_transaction_date,
    max(transaction_date)                      as latest_transaction_date,
    max(modified_at)                           as latest_modified_at,
    cast(current_timestamp as timestamp)       as built_at
from {{ ref('fct_vehicle_transactions') }}
