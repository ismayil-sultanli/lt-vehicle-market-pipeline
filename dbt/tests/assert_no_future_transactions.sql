-- A document cannot be issued after it was extracted.
select transaction_id, transaction_date, extracted_at
from {{ ref('stg_regitra__transactions') }}
where transaction_date > cast(extracted_at as date) + 1
