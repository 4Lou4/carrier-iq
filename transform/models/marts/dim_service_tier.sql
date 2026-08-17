-- One row per service tier.
--
-- ``tier_rank`` encodes the ordering, which is real information: the tiers are a
-- ladder, and a query that wants "premium and above" needs to express that without
-- hard-coding a list of strings. What this dimension deliberately does *not* carry
-- is any weighting between margin and quality — that is commercial policy, it is
-- prescribed rather than derived, and it does not belong in a dimension table.

select
    md5(service_tier) as service_tier_key,
    service_tier,
    case service_tier
        when 'economy' then 1
        when 'standard' then 2
        when 'premium' then 3
        when 'critical' then 4
    end as tier_rank,
    count(*) as attempt_count

from {{ ref('stg_call_events') }}
group by service_tier
