-- Where the purchase rate resolved, it must sit strictly below the sale rate.
--
-- A violation means the route is being sold at a loss, which is a real business
-- event rather than a bug — so in production this would be an alert on a monitored
-- table rather than a hard failure. It is a failing test here because the generator
-- never produces one, which makes it a genuine regression detector: if it fires, the
-- rate logic changed.

select
    call_attempt_key,
    sell_rate_eur_per_min,
    buy_rate_eur_per_min,
    margin_eur_per_min
from {{ ref('fct_call_attempt') }}
where has_buy_rate
  and buy_rate_eur_per_min >= sell_rate_eur_per_min
