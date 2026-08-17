-- Observability, not a gate. One row, describing how thin the decision mart is.
--
-- This model exists because of a mistake worth keeping visible. The first version of
-- the generator drew the four parts of the decision key independently, which spread
-- traffic over their cartesian product and left the mart at 1.6 attempts per slot,
-- median 1 — every answer rate in it was 0 or 1. Nothing failed. No test fired. The
-- mart was full of numbers and none of them meant anything.
--
-- The lesson is that a warehouse needs to publish the *reliability* of its measures
-- alongside the measures, or a consumer cannot tell a rate computed on four hundred
-- attempts from one computed on two. So this is a first-class model rather than an
-- ad-hoc query, and the README quotes it.
--
-- It is deliberately not a test. Thin slots are the normal condition of this domain —
-- on the system this models, 36.7% of carrier-destination pairs had fewer than thirty
-- answered calls over ten weeks. Failing a build on that would be failing it on
-- reality. What downstream owes is a shrinkage estimator and an explicit decidable
-- perimeter, which is step 6, not a threshold pretending the problem is absent.

select
    count(*) as slots,
    sum(attempts) as attempts,

    round(avg(attempts), 2) as mean_attempts_per_slot,
    -- Standard ordered-set aggregate rather than DuckDB's median(), for the same
    -- reason the marts use `filter`: step 2 moves this to Postgres.
    percentile_cont(0.5) within group (order by attempts) as median_attempts_per_slot,
    max(attempts) as max_attempts_per_slot,

    -- Thirty answered attempts is the point below which a rate stops carrying
    -- information, and it is also the smoothing constant the downstream shrinkage
    -- estimator is tuned to. Reporting the share above it says, in one number, how
    -- much of this mart can be read directly and how much needs shrinking first.
    count(*) filter (where attempts >= 30) as slots_at_or_above_30,
    round(count(*) filter (where attempts >= 30) / count(*)::double, 4) as share_at_or_above_30,

    round(avg(buy_rate_coverage), 4) as mean_buy_rate_coverage,
    min(interval_start_utc) as first_interval_utc,
    max(interval_start_utc) as last_interval_utc

from {{ ref('agg_routing_interval') }}
