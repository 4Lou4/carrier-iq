-- Both answer rates are shares of the same denominator, so they belong in [0, 1],
-- and the human rate can never exceed the raw one.
--
-- The third condition is the useful one: it catches a division that picked up the
-- wrong denominator, which is the single most common way an aggregate goes wrong
-- while still looking plausible.

select
    interval_start_utc,
    carrier_code,
    destination_code,
    attempts,
    answer_rate,
    human_answer_rate,
    buy_rate_coverage
from {{ ref('agg_routing_interval') }}
where answer_rate not between 0 and 1
   or human_answer_rate not between 0 and 1
   or buy_rate_coverage not between 0 and 1
   or human_answer_rate > answer_rate
