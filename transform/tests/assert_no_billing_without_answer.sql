-- A call that was not answered cannot have billed time.
--
-- This is the kind of rule that never breaks until an upstream mapping changes a
-- disposition label, and then breaks silently on revenue.

select
    call_attempt_key,
    disposition,
    billable_seconds
from {{ ref('fct_call_attempt') }}
where not is_answered
  and billable_seconds > 0
