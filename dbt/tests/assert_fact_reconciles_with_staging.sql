-- The incremental fact must contain exactly the documents present in staging.
with counts as (
    select
        (select count(*) from {{ ref('stg_regitra__transactions') }}) as staging_rows,
        (select count(*) from {{ ref('fct_vehicle_transactions') }})  as fact_rows
)

select * from counts where staging_rows <> fact_rows
