-- The decision mart's grain, asserted.
--
-- Uniqueness here is a property of five columns together, which no single-column
-- test can express. Written by hand rather than pulled in with dbt_utils: one macro
-- package is not worth a dependency this project would otherwise not have.
--
-- This is also the last line of defence for the deduplication in staging. If a
-- duplicate ever survived, it would not show up as a wrong count in the mart — it
-- would show up here, as two rows claiming the same decision slot.

select
    interval_start_utc,
    carrier_code,
    destination_code,
    origin_cc,
    service_tier,
    count(*) as rows_in_slot
from {{ ref('agg_routing_interval') }}
group by
    interval_start_utc,
    carrier_code,
    destination_code,
    origin_cc,
    service_tier
having count(*) > 1
