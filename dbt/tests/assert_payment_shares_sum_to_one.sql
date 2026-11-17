-- Shares within a month and price segment must add up to 100%.
select transaction_month, price_segment, sum(share_of_segment) as total_share
from {{ ref('agg_payment_methods_monthly') }}
group by all
having abs(sum(share_of_segment) - 1) > 0.001
