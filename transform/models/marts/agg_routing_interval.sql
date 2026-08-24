-- The decision mart. Grain: 15 min x carrier x destination x origin x tier.
--
-- This is the level at which a routing choice is actually made, which is why the
-- warehouse serves it as a table rather than leaving every consumer to re-derive it.
--
-- The three joins are the star being used for what it is for. The fact table carries
-- only hashed keys; the readable codes live in the dimensions, and this is where they
-- are brought back together — once, here, rather than in every consumer's query.
--
-- They are INNER joins on purpose. A LEFT join would quietly return a row with a null
-- carrier if a dimension ever stopped covering the fact, and the mart would keep
-- looking healthy. An INNER join plus the relationships tests in _marts.yml makes
-- that breakage loud instead: the tests fail before anyone reads a wrong number.
--
-- Every conditional count uses the standard ``filter`` clause rather than DuckDB's
-- ``count_if``. Step 2 moves this warehouse to Postgres, and portable SQL that costs
-- nothing today saves a rewrite then.

select
    f.interval_start_utc,
    c.carrier_code,
    d.destination_code,
    f.origin_cc,
    t.service_tier,

    count(*) as attempts,
    count(*) filter (where is_answered) as answered_attempts,
    count(*) filter (where is_human_answered) as human_answered_attempts,

    -- Both rates, always. The raw one is what the industry quotes; the human one is
    -- what is true. The gap between them is itself the fraud signal, so collapsing
    -- them into a single "quality" column would destroy the only measure that
    -- distinguishes a good route from a route that merely reports well.
    count(*) filter (where is_answered) / count(*)::{{ dbt.type_float() }} as answer_rate,
    count(*) filter (where is_human_answered) / count(*)::{{ dbt.type_float() }} as human_answer_rate,

    sum(billable_seconds) as billable_seconds,
    sum(billable_minutes) as billable_minutes,
    avg(billable_seconds) filter (where is_human_answered) as avg_human_call_seconds,

    sum(billable_minutes * sell_rate_eur_per_min) as revenue_eur,

    -- Cost and margin are summed over the attempts whose purchase rate resolved, and
    -- ``buy_rate_coverage`` says what share that was. Reporting a margin without its
    -- coverage is how an unreliable number gets treated as a reliable one.
    sum(billable_minutes * buy_rate_eur_per_min) filter (where has_buy_rate) as cost_eur,
    sum(billable_minutes * margin_eur_per_min) filter (where has_buy_rate) as margin_eur,
    count(*) filter (where has_buy_rate) / count(*)::{{ dbt.type_float() }} as buy_rate_coverage

from {{ ref('fct_call_attempt') }} f
inner join {{ ref('dim_carrier') }} c using (carrier_key)
inner join {{ ref('dim_destination') }} d using (destination_key)
inner join {{ ref('dim_service_tier') }} t using (service_tier_key)
group by
    f.interval_start_utc,
    c.carrier_code,
    d.destination_code,
    f.origin_cc,
    t.service_tier
