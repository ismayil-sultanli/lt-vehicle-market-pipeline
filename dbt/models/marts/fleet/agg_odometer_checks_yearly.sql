-- How often a passenger car arrives with a lower odometer reading than at its
-- previous periodic inspection.
select
    inspection_year,
    count(*)                                                              as compared_pairs,
    count(*) filter (where is_lower_reading)                              as lower_reading_pairs,
    count(*) filter (where is_suspected_rollback)                         as suspected_rollbacks,
    cast(
        round(count(*) filter (where is_suspected_rollback) / count(*), 5) as double
    )                                                                     as suspected_rollback_rate,
    cast(
        round(median(-distance_km) filter (where is_suspected_rollback)) as integer
    )                                                                     as median_rollback_km
from {{ ref('int_inspections__odometer_intervals') }}
group by all
