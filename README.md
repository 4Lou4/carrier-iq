# carrier-iq

**An end-to-end data platform on synthetic telecom routing events.** Raw events land
through `dlt`, a DuckDB warehouse holds them, and `dbt` turns them into a star schema
whose tests block the merge rather than decorate a dashboard.

```
generator  →  dlt (extract + load)  →  DuckDB (raw)  →  dbt (transform + test)  →  star schema
```

Nothing here is real. Carriers, destinations, tariffs and traffic are all produced by
the seeded generator in `src/carrier_iq/generator.py`.

---

## Why this project exists

I built a routing decision-support system for a wholesale telecom carrier, in
production, on thirty million calls. The hard part was never the model — it was the
data underneath it. An audit at the start of that project found the **purchase rate
missing on 20.5% of billable calls**, concentrated on particular carriers and
particular periods. A model trained on that would have learned that some carriers
have no cost, therefore infinite margin, and would have recommended them
systematically. Nothing in the training metrics would have shown it.

So this platform is built the way that experience says it has to be built: the data
quality gate comes before the model, and it is a gate — not a report.

**The generator injects the same two defects on purpose.** A share of events carry no
purchase rate, and a share are delivered twice. The dbt tests exist to catch exactly
those, and they run in CI as a merge-blocking step. A test that cannot fail proves
nothing, so the fixtures make sure these can.

---

## The dimensional model

**Grain first.** One row in the fact table is one call attempt. Every aggregate is
derived from that grain; choosing it before drawing tables is the decision that
costs a rewrite if you get it wrong.

| Layer | Model | Grain |
|---|---|---|
| staging | `stg_call_events` | one call attempt, deduplicated, pinned to UTC |
| dimensions | `dim_carrier`, `dim_destination`, `dim_service_tier` | one row per entity |
| fact | `fct_call_attempt` | one call attempt |
| mart | `agg_routing_interval` | 15 min × carrier × destination × origin × tier |
| observability | `dq_interval_density` | one row: how thin the decision mart is |

The mart's grain is the **decision grain**: it is the level at which a routing choice
is actually made, so it is the level the warehouse has to serve. Origin sits in the
key because some carriers price the same destination differently depending on where
the call originates.

---

## What it produces

A single `python -m carrier_iq.ingest && cd transform && dbt build --profiles-dir .`
on a laptop, from an empty directory:

```
raw.call_events            843 290 rows   ← at-least-once, duplicates included
analytics.fct_call_attempt 840 000 rows   ← exactly 7 × 120 000 after deduplication
analytics.agg_routing_interval  27 782 slots

dq_interval_density
  mean_attempts_per_slot    30.24
  median_attempts_per_slot  15
  max_attempts_per_slot     487
  share_at_or_above_30      0.2557
  mean_buy_rate_coverage    0.9217

dbt build   PASS=60  ERROR=0
```

The first two numbers are the deduplication test earning its place: 843 290 delivered
rows collapse to *exactly* 840 000 distinct events, which is seven days at the
configured volume, to the row.

---

## The mistake this project is shaped around

The first version of the generator drew the four parts of the decision key —
destination, origin, tier, carrier — independently. It looked properly skewed. It was
wrong, and nothing caught it: no test failed, no model errored, and the warehouse
filled with plausible numbers.

Drawing the keys independently spreads traffic across their **cartesian product**.
840 000 attempts landed in 512 254 decision slots — **1.6 attempts per slot, median
1**. Every answer rate in the decision mart was 0 or 1. The mart was noise wearing the
costume of a measurement.

The first fix was wrong too. I assumed a volume problem, tripled the volume and
sharpened the weights, and moved the density from 1.09 to 1.6. Measuring that failure
is what showed the problem was structural: **real routing is sparse, not cartesian.**
On the system this models, only 255 decision groups were ever observed, each with 2.2
eligible carriers on average, 39% of them served by a single carrier.

So the generator now builds a fixed `RoutingCatalogue` and draws a *group* from it,
rather than drawing four keys and hoping they combine into something a routing plan
would contain. Same volume, 27 782 slots instead of 512 254 — mean 30, median 15. The
catalogue reproduces the observed shape: 2.12 carriers per group, 33% single-carrier.

One more thing was wrong in the original, and it is the kind of error that survives
review: the weights came from `random() ** concentration`, which *looks* like a skew
and is not. Over twelve carriers it gave the busiest one about 30% of traffic, where
the real system had three carriers on 92%. A rank-based power law — Zipf — has one
interpretable parameter and hits the observed shape.

**And the fix stops deliberately short of making the problem disappear.** Three
quarters of slots still hold fewer than thirty attempts, because that is the domain:
36.7% of carrier–destination pairs on the real system had fewer than thirty answered
calls over ten weeks. So `dq_interval_density` publishes the thinness as a measure and
is pointedly *not* a test. Failing a build on thin data would be failing it on
reality. What the thinness needs is a shrinkage estimator and an explicit decidable
perimeter — which is [`regret-eval`](https://github.com/4Lou4/regret-eval), wired in
at step 6.

---

## Two measures that must not be confused

| Measure | Definition | Why both |
|---|---|---|
| `answer_rate` | answered attempts / attempts | The number the industry quotes. |
| `human_answer_rate` | attempts answered **by a person** / attempts | The number that means something. |

A machine pickup, or a fraudulently generated answer, counts as "answered" on the
ticket while nobody ever spoke. A system optimising the raw answer rate therefore
rewards the worst routes, and does it more efficiently the better it is trained.
Both measures are materialised, and the gap between them is itself a signal.

---

## Run it

```bash
uv venv --python 3.11
uv pip install -e ".[dev,dbt]"

pytest                                  # 26 tests, including a real dlt → DuckDB run
python -m carrier_iq.ingest             # generator → dlt → DuckDB, ~2 min for a week
cd transform
dbt build --profiles-dir .              # 8 models + ~57 tests, red on any defect
```

### On PostgreSQL instead

DuckDB is the default and needs nothing running. Postgres is the step-2 warehouse,
brought in by the trigger ADR-001 named — an orchestrator runs tasks in parallel, and
DuckDB takes a single writer lock on its file.

```bash
cp .env.example .env                    # then change the password
docker compose up -d                    # Postgres on port 55432, not 5432

python -m carrier_iq.ingest --destination postgres
cd transform
dbt build --profiles-dir . --target postgres
```

Both warehouses produce the same numbers, and that was verified by comparing them
rather than by both builds going green: same slot count, same attempt count, same mean
answer rate to six decimals, same first and last bucket. See ADR-003 — the `date_bin`
origin is the place where this could have gone quietly wrong.

To watch the quality gate do its job, load a degraded window and rebuild:

```python
from datetime import date
from carrier_iq.generator import GeneratorConfig
from carrier_iq.ingest import load
load(date(2026, 3, 8), 5, config=GeneratorConfig(missing_buy_rate_share=0.60))
```

`dbt build` then exits non-zero on `assert_buy_rate_coverage_above_threshold`, and the
decision mart and its tests are **skipped** rather than rebuilt — the bad rows never
reach the layer anyone reads. That is the difference between a gate and a dashboard.

## Decisions

Architecture decisions are recorded one page at a time in [`docs/adr/`](docs/adr/).
The first one explains why the warehouse is DuckDB and not Postgres, and names the
exact limit that will justify changing it.

MIT licensed.
