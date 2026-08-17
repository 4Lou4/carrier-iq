-- A person cannot have picked up a call that was never answered.
--
-- The two flags come from different upstream fields, so nothing structural keeps
-- them consistent. If this ever fails, the human answer rate — the measure the whole
-- decision rests on — has become larger than the raw one, which is impossible.

select
    call_attempt_key,
    disposition,
    is_answered,
    is_human_answered
from {{ ref('fct_call_attempt') }}
where is_human_answered
  and not is_answered
