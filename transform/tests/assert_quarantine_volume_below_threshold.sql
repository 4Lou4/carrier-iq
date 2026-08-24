-- The test that makes the dead letter queue honest.
--
-- A quarantine solves the problem of one bad delivery stopping a good run. It also
-- creates a new one: rejected rows leave silently, so a broken upstream shows up as
-- totals that are quietly short rather than as a failure. The queue converts a loud
-- problem into a quiet one, and this test converts it back.
--
-- Two bounds, for two different failures.
--
-- Above 1%: upstream has started producing unreadable rows at five times the usual
-- rate, and the build stops rather than quietly undercounting.
--
-- At exactly zero: the mechanism itself has stopped working. Either the generator no
-- longer injects malformed deliveries or the macro no longer matches them, and in
-- both cases the quarantine has become decoration. It is the same rule the coverage
-- gate follows: a test that cannot fail proves nothing, and a queue that never holds
-- anything proves nothing either.

with volumes as (

    select
        (select count(*) from {{ ref('stg_call_events_quarantine') }}) as quarantined,
        (select count(*) from {{ source('raw', 'call_events') }}) as delivered

),

share as (

    select
        quarantined,
        delivered,
        quarantined / nullif(delivered, 0)::{{ dbt.type_float() }} as quarantined_share
    from volumes

)

select *
from share
where quarantined_share > 0.01
   or quarantined = 0
