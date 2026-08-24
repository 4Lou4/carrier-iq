"""Extract and load: synthetic events → DuckDB, through dlt.

Run it:

    python -m carrier_iq.ingest                 # 7 days into warehouse.duckdb
    python -m carrier_iq.ingest --days 30       # a longer window
    python -m carrier_iq.ingest --start 2026-04-01 --days 7

Two decisions in here are worth more than the code, because they are the ones an
interviewer asks about.

**Raw is a faithful record, so duplicates land.** dlt can deduplicate at load time.
It is switched off here, deliberately, by passing an empty ``primary_key`` to the
incremental cursor. If the loader silently dropped the duplicated deliveries, the
warehouse would lose the evidence that duplicates ever arrived and the defect rate
would become unmeasurable. Deduplication belongs one layer down, in a transform that
is versioned, tested, and can fail a build — not in the loader.

**Loading is incremental on ``occurred_at``, with a closed boundary.** dlt keeps the
high-water mark in its own state, so re-running does not re-load the whole window.
The boundary is inclusive (``>= last_value``), which means the events sitting exactly
on the previous maximum are read again on the next run. That is deliberate, and the
alternative is worse: an exclusive boundary would drop any genuinely new event that
happens to share that timestamp, and with sixty thousand events spread over
eighty-six thousand seconds, collisions are not rare — they are the norm. Losing real
rows to avoid re-reading a few is the wrong trade.

So the raw layer is **at-least-once** by design. A pipeline re-run and an upstream
re-delivery are the same phenomenon, and production cannot tell them apart either.
Exactly one place removes duplicates — the staging model — and a test asserts it.

The honest cost of the current shape: the generator still produces every event before
dlt filters it. That is cheap at sixty thousand events a day — a fortnight loads in
about two minutes — and it would be untenable at five hundred million. Hitting that
limit is what step 3 of this project is for.
"""

from __future__ import annotations

import argparse
import os
from datetime import date

import dlt

from carrier_iq.generator import GeneratorConfig, generate_days

DEFAULT_START = date(2026, 3, 1)
#: A week. Long enough to show a weekly pattern and to make a backfill meaningful,
#: short enough that the slots in the decision mart are not spread too thin — see the
#: sparsity note in carrier_iq.generator.
DEFAULT_DAYS = 7
WAREHOUSE = "warehouse.duckdb"
DATASET = "raw"


@dlt.resource(name="call_events", write_disposition="append")
def call_events(
    start: date = DEFAULT_START,
    n_days: int = DEFAULT_DAYS,
    config: GeneratorConfig | None = None,
    # noqa B008: ruff objects to a function call in a default argument, and it is
    # right in general — but dlt binds its incremental cursor by inspecting the
    # parameter defaults, so this is the framework's required shape, not a mistake.
    # Moving it to a module-level singleton would share one cursor across every
    # pipeline instance, which is exactly what the tests isolate against.
    occurred_at=dlt.sources.incremental("occurred_at", primary_key=()),  # noqa: B008
):
    """One dlt resource: the raw call-attempt stream.

    ``primary_key=()`` disables dlt's boundary deduplication. See the module
    docstring — this is a choice about what "raw" means, not an oversight.
    """
    yield from generate_days(start, n_days, config)


def _postgres_destination():
    """The step-2 warehouse, addressed entirely through environment variables.

    Nothing here has a default password. If ``POSTGRES_PASSWORD`` is unset the call
    fails immediately with a readable message, rather than falling back to something
    that happens to work on one machine and nowhere else.
    """
    missing = [k for k in ("POSTGRES_PASSWORD",) if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"{', '.join(missing)} is not set. Copy .env.example to .env and start the "
            "warehouse with `docker compose up -d`."
        )
    return dlt.destinations.postgres(
        "postgresql://{user}:{password}@{host}:{port}/{db}".format(
            user=os.environ.get("POSTGRES_USER", "carrier_iq"),
            password=os.environ["POSTGRES_PASSWORD"],
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=os.environ.get("POSTGRES_PORT", "55432"),
            db=os.environ.get("POSTGRES_DB", "carrier_iq"),
        )
    )


def build_pipeline(
    warehouse: str = WAREHOUSE,
    pipelines_dir: str | None = None,
    destination: str = "duckdb",
) -> dlt.Pipeline:
    """Build the pipeline.

    ``pipelines_dir`` exists so a test can get its own incremental state. dlt keeps
    the high-water mark on disk keyed by pipeline name, so without it two tests
    would silently share a cursor and the second one would load nothing.

    ``destination`` selects the warehouse. DuckDB stays the default: it needs no
    server, so the whole test suite and the whole CI run without Docker. Postgres is
    the step-2 target, and the pipeline name changes with it — dlt keys its
    high-water mark by pipeline name, so sharing one name across two warehouses would
    let a DuckDB run convince a Postgres run that it had already loaded everything.
    """
    if destination == "postgres":
        return dlt.pipeline(
            pipeline_name="carrier_iq_postgres",
            destination=_postgres_destination(),
            dataset_name=DATASET,
            pipelines_dir=pipelines_dir,
        )
    if destination != "duckdb":
        raise ValueError(f"unknown destination {destination!r}; expected duckdb or postgres")
    return dlt.pipeline(
        pipeline_name="carrier_iq",
        destination=dlt.destinations.duckdb(warehouse),
        dataset_name=DATASET,
        pipelines_dir=pipelines_dir,
    )


def load(
    start: date = DEFAULT_START,
    n_days: int = DEFAULT_DAYS,
    warehouse: str = WAREHOUSE,
    config: GeneratorConfig | None = None,
    pipelines_dir: str | None = None,
    destination: str = "duckdb",
):
    pipeline = build_pipeline(warehouse, pipelines_dir, destination)
    return pipeline.run(call_events(start=start, n_days=n_days, config=config))


def main() -> None:
    parser = argparse.ArgumentParser(description="Load synthetic call events.")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--warehouse", default=WAREHOUSE)
    parser.add_argument(
        "--destination",
        choices=("duckdb", "postgres"),
        default="duckdb",
        help="Where to load. DuckDB needs nothing running; postgres needs the container up.",
    )
    parser.add_argument(
        "--events-per-day",
        type=int,
        default=None,
        help=(
            "Override the generated volume. CI uses a small value: the pipeline's "
            "correctness does not depend on volume, and a merge gate that takes four "
            "minutes stops being run."
        ),
    )
    args = parser.parse_args()

    config = (
        GeneratorConfig(events_per_day=args.events_per_day)
        if args.events_per_day is not None
        else None
    )
    info = load(
        start=args.start,
        n_days=args.days,
        warehouse=args.warehouse,
        config=config,
        destination=args.destination,
    )
    print(info)


if __name__ == "__main__":
    main()
