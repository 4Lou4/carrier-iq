# ADR-003: Add PostgreSQL as a second target, keep DuckDB as the default

*Status: accepted. Revises ADR-001, which chose DuckDB and named the triggers that
would bring Postgres in.*

## Context

ADR-001 chose DuckDB and listed what would change the decision. The first trigger was
concurrent writes, and it said plainly: *"which step 2 hits, which is why step 2 is
where Postgres arrives."* Step 2 adds an orchestrator, and an orchestrator runs tasks
in parallel against one warehouse. DuckDB takes a single writer lock on its file, so
two concurrent tasks do not queue — the second one fails.

## Decision

Postgres becomes a **second dbt target**, not a replacement. `dev` (DuckDB) stays the
default, and that choice is load-bearing:

- The full test suite and the whole CI run **without Docker**. A portfolio repository
  that needs a container running before it does anything loses the reader who was
  willing to give it five minutes.
- Anyone can clone, `uv sync`, and get a green build offline.
- Postgres is one flag away: `--target postgres`, with the container up.

The warehouse runs from `docker-compose.yml`, on published port **55432** rather than
5432, because a locally installed Postgres would take 5432 and the collision produces
an error that reads like bad credentials.

No password is written anywhere in the repository. Every field of the Postgres target
reads an environment variable, `.env` is gitignored, `.env.example` carries dummy
values and is committed, and the compose file **refuses to start** if
`POSTGRES_PASSWORD` is unset rather than falling back to a default.

## What the migration actually cost: three breaks, and only one was predicted

ADR-001 predicted one portability problem. There were three, and the two unpredicted
ones are the more interesting.

| Break | Why it happened | Fix |
|---|---|---|
| `time_bucket` | DuckDB-only. **This one was predicted** in ADR-001. | `interval_bucket` macro, dispatched per adapter: `time_bucket` on DuckDB, `date_bin` on Postgres. |
| `::double` | DuckDB accepts the short alias; Postgres requires `double precision`. Not predicted. | `{{ dbt.type_float() }}`, dbt's own cross-database type macro. |
| `round(x, 2)` | Postgres defines `round(numeric, int)` and **has no** `round(double precision, int)`. DuckDB accepts both. Not predicted, and it only surfaced at build time on one model. | Cast to `numeric` before rounding. |

The lesson worth carrying: **writing portable SQL by intention caught the case we
thought about and missed two we did not.** The conditional aggregates written as
`count(*) filter (...)` instead of `count_if(...)` did port unchanged, so the effort
was not wasted — it was just incomplete. Only running on the second warehouse found
the rest.

### The `date_bin` origin, which is where this could have gone quietly wrong

`date_bin` counts whole intervals from an explicit origin, and takes it as an
argument. With an origin of `2000-01-01 00:00:00`, buckets land on :00, :15, :30 and
:45 — the same boundaries DuckDB's `time_bucket` produces. An arbitrary origin would
have shifted every bucket by a constant offset, **silently**: the models would build,
the tests would pass, and the two warehouses would disagree about which interval an
event belongs to.

That is why the migration was verified by **comparing outputs**, not by both builds
going green. On the same three days of data, both warehouses return 5 025 slots,
11 976 attempts, an identical mean answer rate to six decimals, and the same first and
last bucket. Two green builds prove that two queries ran; equal numbers prove they
computed the same thing.

## The trade-off we accept

Two targets means two ways for the project to be configured, and a reader has to know
which one they are on. That is bought in exchange for a repository that still runs
with nothing installed, and it is the right way round: the cost falls on the person
who chose to start a container, not on the person evaluating the project.
