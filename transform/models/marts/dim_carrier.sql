-- One row per carrier.
--
-- The key is a hash of the natural key rather than a sequence. Two reasons, and the
-- second is the one that matters: a hash lets the fact table be built without a
-- lookup join, and it is the prerequisite for turning this into a slowly changing
-- dimension in step 4 without renumbering anything that already points at it.

select
    md5(carrier_code) as carrier_key,
    carrier_code,
    min(occurred_at_utc) as first_seen_at_utc,
    max(occurred_at_utc) as last_seen_at_utc,
    count(*) as attempt_count

from {{ ref('stg_call_events') }}
group by carrier_code
