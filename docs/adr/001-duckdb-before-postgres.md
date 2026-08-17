# ADR-001 — DuckDB as the first warehouse, not Postgres

- **Status** — accepted
- **Date** — 2026-08-17
- **Scope** — step 1 of the platform: ingestion, warehouse, dimensional model, tests

## Context

The platform needs a warehouse to hold raw call events and serve a dimensional model
on top of them. The workload is analytical: full scans over a fact table, grouped
aggregation to a 15-minute decision grain, no concurrent writers, no transactional
reads. At this stage the volume is under a million rows.

The temptation is to start with the destination architecture — Postgres now, a
lakehouse later — on the grounds that the migration will be painful. That reasoning
inverts the cost: a warehouse that needs a running server, a connection string and a
secret costs something on every single run, including in CI, and it buys nothing that
this workload asks for.

## Decision

**DuckDB, as a single file in the repository working tree.** dbt targets it through
`dbt-duckdb`, and the file is regenerated from the seeded generator rather than backed
up.

## Options considered

| Option | Why it was not chosen |
|---|---|
| **Postgres in Docker** | Row-oriented storage, so the grouped scans this workload is made of are its worst case. Adds a container, a service to wait for in CI, and a credential to manage — three moving parts serving zero current requirement. |
| **A cloud warehouse** (Snowflake, BigQuery, Redshift) | Real money, a network round-trip on every dbt run, and a vendor account in the critical path of a portfolio project. Also removes the ability to work offline. |
| **SQLite** | No columnar storage and no window-function performance to speak of. It would be a smaller version of the Postgres mistake. |
| **Parquet files + Polars, no warehouse** | Workable, but it gives up SQL — and SQL is the interface dbt speaks, the interface analysts speak, and the one this project is partly built to demonstrate. |

## Consequences

**What this buys.** `git clone`, `uv pip install`, two commands, and the whole
warehouse exists — including in CI, with no service container and no secret. The
entire dbt suite runs in under three seconds, which is what makes it realistic to
gate every merge on it rather than run it nightly and hope.

**What this costs.** One writer at a time and no concurrency, so this cannot be a
shared warehouse. No network access, so nothing outside this machine can query it. And
DuckDB-specific SQL is a live risk: `time_bucket` has no Postgres equivalent, and it
is used in the staging model. That risk is managed rather than ignored — every
conditional aggregate in the marts uses the standard `filter` clause instead of
DuckDB's `count_if`, precisely so the migration is confined to the few places that
genuinely needed a DuckDB feature.

## What will trigger the revision

This decision gets revisited when one of these becomes true, and not before:

1. **A second consumer needs concurrent access.** The moment an orchestrator writes
   while a dashboard reads, a single-writer file is the wrong shape. This is what
   step 2 hits, which is why step 2 is where Postgres arrives.
2. **The working set stops fitting in memory.** DuckDB spills to disk, but a
   deliberate skew exercise at 30–50 GB is step 3, and that is where a distributed
   engine earns its complexity.
3. **State has to survive the machine.** As long as the warehouse is a pure function
   of a seeded generator, losing it costs two minutes. The day it holds anything that
   cannot be regenerated, it needs a real server and real backups.

Until one of those happens, migrating would be paying a known cost for a benefit
nobody has asked for yet.
