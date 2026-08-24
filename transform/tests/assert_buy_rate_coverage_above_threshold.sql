-- THE GATE.
--
-- Fails the build when the share of attempts with a resolved purchase rate falls
-- below 85%. This is the test the whole project is built around.
--
-- The audit that motivated this platform found the purchase rate missing on 20.5% of
-- billable calls, concentrated on particular carriers and particular periods. A model
-- trained on that would have learned that those carriers have no cost, therefore
-- infinite margin, and would have recommended them systematically — and every
-- training metric would have looked fine, because the metrics were computed on the
-- same wrong data.
--
-- So this is not a monitoring query. It is a merge-blocking gate, and it is the
-- reason the data quality step comes before the model rather than after it.

with coverage as (

    select
        count(*) as attempts,
        count(*) filter (where has_buy_rate) as with_buy_rate,
        count(*) filter (where has_buy_rate) / count(*)::{{ dbt.type_float() }} as coverage
    from {{ ref('fct_call_attempt') }}

)

select *
from coverage
where coverage < 0.85
