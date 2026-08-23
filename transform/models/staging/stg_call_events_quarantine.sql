-- The dead letter queue.
--
-- A pipeline has three options when a delivery arrives unreadable: let it through,
-- fail the load, or set it aside. The first corrupts every aggregate downstream. The
-- second lets one bad row stop a run that is otherwise fine, which is how teams end
-- up disabling the check. This model is the third: the row is kept, labelled with the
-- reason it was rejected, and counted.
--
-- Keeping it matters as much as rejecting it. A quarantine you cannot read is a
-- deletion with extra steps: when someone asks why yesterday's totals are short, the
-- answer has to be a query, not a shrug.
--
-- The volume is itself under test — see assert_quarantine_volume_below_threshold.
-- A dead letter queue that grows silently is worse than none, because it converts a
-- loud upstream failure into a quiet undercount.

with flagged as (

    select
        *,
        {{ quarantine_reason() }} as quarantine_reason
    from {{ source('raw', 'call_events') }}

)

select
    event_id,
    occurred_at,
    carrier_code,
    destination_code,
    origin_cc,
    service_tier,
    disposition,
    billable_seconds,
    sell_rate_eur_per_min,
    buy_rate_eur_per_min,
    quarantine_reason,
    -- Kept so a rejected delivery can be traced back to the load that carried it.
    _dlt_load_id,
    _dlt_id
from flagged
where quarantine_reason is not null
