-- The fact table. Grain: one row per call attempt.
--
-- Choosing the grain before drawing the tables is the decision that costs a rewrite
-- if you get it wrong, so it is stated first and never bent: everything coarser in
-- this warehouse is derived from this table, never alongside it.
--
-- The dimension keys are recomputed as hashes rather than joined. That is not a
-- shortcut around referential integrity — the relationships tests in _marts.yml
-- prove it holds, and they would fail if a dimension ever stopped covering the fact.

select
    event_id as call_attempt_key,

    md5(carrier_code) as carrier_key,
    md5(destination_code) as destination_key,
    md5(service_tier) as service_tier_key,

    -- Origin stays a degenerate dimension: it is part of the decision key but it
    -- carries no attribute of its own, so a table for it would hold nothing.
    origin_cc,

    occurred_at_utc,
    interval_start_utc,

    disposition,
    is_answered,
    is_human_answered,

    billable_seconds,
    billable_minutes,
    sell_rate_eur_per_min,
    buy_rate_eur_per_min,
    has_buy_rate,
    margin_eur_per_min

from {{ ref('stg_call_events') }}
