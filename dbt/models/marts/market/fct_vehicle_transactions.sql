{{
    config(
        materialized = 'incremental',
        unique_key = 'transaction_id',
        incremental_strategy = 'delete+insert',
        on_schema_change = 'fail',
        post_hook = [
            "delete from {{ this }} where transaction_id not in (select transaction_id from {{ ref('stg_regitra__transactions') }})"
        ]
    )
}}

-- Fact table, one row per transaction document.
--
-- Incremental on *arrival* time (`extracted_at`), not on the source's
-- `modified_at`: backfills and gap repairs land old records late, and a
-- watermark on the business timestamp would silently skip them. Every row
-- loaded since the previous build is merged by key, so re-pulled partitions are
-- idempotent. The post-hook removes documents the publisher has withdrawn.
--
-- Run with --full-refresh after changing a reference seed.

select *
from {{ ref('int_transactions__enriched') }}

{% if is_incremental() %}
where extracted_at > (select coalesce(max(extracted_at), timestamp '1900-01-01') from {{ this }})
{% endif %}
