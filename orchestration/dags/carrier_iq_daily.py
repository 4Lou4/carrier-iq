"""One logical day of call events, loaded and transformed.

Why this DAG is shaped the way it is
------------------------------------
The whole point of an orchestrator here is not that it runs things on a timer. Cron
does that. It is that **a run is bound to a date rather than to "now"**, which is what
makes a backfill a normal operation instead of a rescue mission.

Every task below reads ``data_interval_start`` — the logical day the run stands for —
and never ``datetime.now()``. Re-running the DAG for 3 March produces exactly what the
original run for 3 March produced, whether it is executed on 3 March or six months
later. That property has a name worth using out loud: the DAG is **idempotent per
logical date**, and it is what ``airflow dags backfill`` relies on.

A task that read ``now()`` would look identical, pass its tests, and silently make
every backfill wrong.

What it does not do, and why
----------------------------
There is no retry on the dbt task beyond one attempt. Retrying a failed data-quality
gate is the wrong instinct: the gate is not flaky, it is a verdict. Re-running it
hoping for a different answer is how a team learns to ignore red builds. The ingestion
task does retry, because a warehouse that is still starting up is genuinely transient.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

# The warehouse the orchestrator writes to. DuckDB takes a single writer lock on its
# file, so it cannot serve parallel tasks — that is the trigger ADR-001 named for
# bringing Postgres in, and it is why this DAG targets Postgres and nothing else.
PROJECT = "/opt/carrier-iq"
TRANSFORM = f"{PROJECT}/transform"

default_args = {
    "retries": 3,
    # Exponential backoff, not a fixed delay. A warehouse that is still coming up
    # needs seconds; a warehouse that is genuinely down should not be hammered every
    # thirty seconds for an hour.
    "retry_delay": pendulum.duration(seconds=30),
    "retry_exponential_backoff": True,
    "max_retry_delay": pendulum.duration(minutes=10),
}

with DAG(
    dag_id="carrier_iq_daily",
    description="Load and transform one logical day of synthetic call events.",
    start_date=pendulum.datetime(2026, 3, 1, tz="UTC"),
    schedule="@daily",
    # No automatic catch-up on unpause. Otherwise pausing the DAG for a week and
    # resuming it launches seven runs at once against one warehouse — which is how a
    # first Airflow deployment usually discovers what concurrency means. Backfills
    # are run deliberately, from the command line.
    catchup=False,
    # One run at a time. The tasks write to the same schema, and dbt is not safe to
    # run twice concurrently against one target.
    max_active_runs=1,
    default_args=default_args,
    tags=["carrier-iq", "step-2"],
) as dag:
    # `{{ data_interval_start }}` is the logical day, injected by Airflow. This is the
    # single line that makes a backfill meaningful: the loader is told which day to
    # produce, so it produces that day and not today's.
    ingest = BashOperator(
        task_id="ingest_one_day",
        bash_command=(
            "python -m carrier_iq.ingest"
            " --start {{ data_interval_start | ds }}"
            " --days 1"
            " --destination postgres"
        ),
        cwd=PROJECT,
    )

    # The quality gate. It runs after the load and it is allowed to fail the run:
    # a merge gate that the orchestrator retries until it passes is not a gate.
    transform = BashOperator(
        task_id="dbt_build",
        bash_command="dbt build --profiles-dir . --target postgres",
        cwd=TRANSFORM,
        retries=0,
    )

    ingest >> transform
