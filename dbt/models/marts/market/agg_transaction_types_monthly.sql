-- Every ownership transfer by category (sale, lease end, inheritance, gift, ...).
select
    transaction_month,
    transaction_category,
    document_type,
    count(*)                                                     as transactions
from {{ ref('fct_vehicle_transactions') }}
group by all
