-- The density summary describes the whole mart, so it is one row by construction.
--
-- If it ever returns more, an ungrouped aggregate has acquired a grouping key and the
-- README is quoting a number that no longer means what it says.

select count(*) as rows_in_summary
from {{ ref('dq_interval_density') }}
having count(*) <> 1
