"""Tests for the extract-and-load step.

These are integration tests: they run dlt for real against a throwaway DuckDB file.
They are slower than the generator tests and they earn it, because the three
properties below are the ones that decide whether a nightly run can be trusted.
"""

from datetime import date

import duckdb
import pytest

from carrier_iq.generator import GeneratorConfig
from carrier_iq.ingest import load

START = date(2026, 3, 1)


@pytest.fixture
def small():
    return GeneratorConfig(events_per_day=800)


@pytest.fixture
def warehouse(tmp_path):
    """A private warehouse *and* a private dlt state directory.

    Both matter: dlt keeps its incremental cursor on disk keyed by pipeline name, so
    a shared state directory would let one test consume another's high-water mark.
    """
    return {
        "warehouse": str(tmp_path / "test.duckdb"),
        "pipelines_dir": str(tmp_path / "dlt"),
    }


def _scalar(warehouse: str, sql: str):
    with duckdb.connect(warehouse, read_only=True) as con:
        return con.sql(sql).fetchone()[0]


def test_load_lands_rows_and_keeps_duplicates(warehouse, small):
    load(START, 2, config=small, **warehouse)
    wh = warehouse["warehouse"]

    rows = _scalar(wh, "select count(*) from raw.call_events")
    distinct = _scalar(wh, "select count(distinct event_id) from raw.call_events")

    assert distinct == 2 * small.events_per_day
    # Raw is a faithful record: the duplicated deliveries must still be there, or
    # the deduplication test one layer down would be asserting nothing.
    assert rows > distinct


def test_reloading_does_not_change_the_deduplicated_count(warehouse, small):
    load(START, 2, config=small, **warehouse)
    wh = warehouse["warehouse"]
    before = _scalar(wh, "select count(distinct event_id) from raw.call_events")

    load(START, 2, config=small, **warehouse)
    after = _scalar(wh, "select count(distinct event_id) from raw.call_events")

    # The raw row count *may* grow: the closed incremental boundary re-reads the
    # events sitting exactly on the previous maximum. What must not move is the set
    # of distinct events, because that is what the warehouse actually means.
    assert after == before


def test_extending_the_window_loads_only_the_new_days(warehouse, small):
    load(START, 2, config=small, **warehouse)
    wh = warehouse["warehouse"]
    before = _scalar(wh, "select count(distinct event_id) from raw.call_events")

    load(START, 4, config=small, **warehouse)
    after = _scalar(wh, "select count(distinct event_id) from raw.call_events")

    assert after - before == 2 * small.events_per_day


def test_days_are_bucketed_in_utc_not_in_local_time(warehouse, small):
    # A day boundary read in local time puts the last hour of every UTC day into the
    # next one. It raises nothing, and it silently shifts every daily aggregate.
    load(START, 3, config=small, **warehouse)
    wh = warehouse["warehouse"]

    utc_days = _scalar(
        wh, "select count(distinct (occurred_at at time zone 'UTC')::date) from raw.call_events"
    )
    assert utc_days == 3
