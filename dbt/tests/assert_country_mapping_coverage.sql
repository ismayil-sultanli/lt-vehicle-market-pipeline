-- The countries seed must cover at least 99.5% of documents. A failure means a
-- new origin country became material and deserves a row in the seed.
with coverage as (
    select
        count(*)                                           as documents,
        count(*) filter (where origin_country = 'Other')   as unmapped
    from {{ ref('int_transactions__enriched') }}
)

select * from coverage where unmapped > 0.005 * documents
