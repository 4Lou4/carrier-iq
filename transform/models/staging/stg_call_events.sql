-- Staging: the one place duplicates are removed and the one place time is pinned.
--
-- The raw layer is at-least-once by design (see src/carrier_iq/ingest.py), so this
-- model is what makes "one row = one call attempt" true. The uniqueness test on
-- event_id in _staging.yml is therefore not decoration: it is the assertion that
-- this deduplication still works, and it fails the build if it stops.

with admissible as (

    -- Unreadable deliveries are held back by stg_call_events_quarantine, using the
    -- same macro. They are excluded here rather than downstream so that the row
    -- numbering below never has to rank a row it cannot order.
    select *
    from {{ source('raw', 'call_events') }}
    where {{ quarantine_reason() }} is null

),

deduplicated as (

    select
        *,
        row_number() over (
            partition by event_id
            -- Deterministic tie-break: keep the earliest delivery. Ordering by the
            -- dlt load id alone is not enough, since one load can carry the same
            -- event twice.
            order by _dlt_load_id, _dlt_id
        ) as _row_in_event

    from admissible

)

select
    event_id,

    -- Time is pinned to UTC here, once, and never re-derived downstream. Casting a
    -- timezone-aware timestamp to a date resolves in the session timezone, which
    -- pushes the last hour of every UTC day into the next one. It raises nothing and
    -- it shifts every daily aggregate.
    occurred_at at time zone 'UTC' as occurred_at_utc,

    -- The decision grain. Fifteen minutes is short enough to catch a degradation
    -- while it still matters, and long enough that the counters keep a statistical
    -- meaning on low-traffic destinations.
    {{ interval_bucket("occurred_at at time zone 'UTC'", 15) }} as interval_start_utc,

    carrier_code,
    destination_code,
    origin_cc,
    service_tier,
    disposition,

    disposition = 'answered' as is_answered,

    -- The measure that means something. A machine pickup, or a fraudulently
    -- generated answer, counts as answered on the ticket while nobody ever spoke —
    -- so a system optimising the raw answer rate rewards the worst routes, and does
    -- it more efficiently the better it is trained.
    coalesce(human_answered, false) as is_human_answered,

    billable_seconds,
    billable_seconds / 60.0 as billable_minutes,

    sell_rate_eur_per_min,
    buy_rate_eur_per_min,
    buy_rate_eur_per_min is not null as has_buy_rate,

    -- Margin stays null where the purchase rate did not resolve. Coalescing it to
    -- zero would turn "the cost is unknown" into "the cost is nothing", which reads
    -- as maximum margin — and that is precisely how a model learns to prefer the
    -- carriers whose tariffs are missing.
    sell_rate_eur_per_min - buy_rate_eur_per_min as margin_eur_per_min

from deduplicated
where _row_in_event = 1
