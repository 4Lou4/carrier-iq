"""Tests for the synthetic generator.

The generator is a fixture for everything downstream, so a silent change here does
not break the pipeline — it quietly changes every number the pipeline produces.
Each test below pins one property the rest of the platform relies on.
"""

from collections import Counter
from datetime import date

import pytest

from carrier_iq.generator import (
    CARRIERS,
    DISPOSITIONS,
    GeneratorConfig,
    generate_day,
    generate_days,
)

DAY = date(2026, 3, 2)


@pytest.fixture
def small():
    return GeneratorConfig(events_per_day=2_000)


@pytest.fixture
def events(small):
    return list(generate_day(DAY, small))


# --- reproducibility: the property a backfill depends on ---


def test_same_day_regenerates_identically(small):
    assert list(generate_day(DAY, small)) == list(generate_day(DAY, small))


def test_a_day_is_identical_alone_and_inside_a_range(small):
    # Backfilling one day must produce exactly what the full run produced for it.
    # If the day were not folded into the seed, re-running a single day would
    # emit different traffic and the backfill would silently rewrite history.
    alone = list(generate_day(date(2026, 3, 3), small))
    inside = [
        e for e in generate_days(DAY, 3, small) if e["occurred_at"].date() == date(2026, 3, 3)
    ]
    assert alone == inside


def test_days_are_not_copies_of_each_other(small):
    first = list(generate_day(DAY, small))
    second = list(generate_day(date(2026, 3, 3), small))
    assert first != second


# --- skew: without it every downstream aggregate looks well-behaved ---


def test_traffic_is_concentrated_on_a_few_carriers(events):
    counts = Counter(e["carrier_code"] for e in events)
    top3 = sum(c for _, c in counts.most_common(3))
    # Real wholesale traffic is far more concentrated than this floor; the point of
    # the assertion is that it is never close to uniform, which would be 25%.
    assert top3 / len(events) > 0.50
    assert len(counts) > 1


def test_every_carrier_code_is_from_the_reference_list(events):
    assert set(e["carrier_code"] for e in events) <= set(CARRIERS)


# --- injected defects: the reason the dbt tests are a merge gate ---


def test_purchase_rate_is_missing_on_roughly_the_configured_share(small):
    events = list(generate_day(DAY, small))
    missing = sum(1 for e in events if e["buy_rate_eur_per_min"] is None)
    share = missing / len(events)
    assert small.missing_buy_rate_share * 0.6 < share < small.missing_buy_rate_share * 1.4


def test_duplicate_event_ids_are_emitted(small):
    events = list(generate_day(DAY, small))
    ids = Counter(e["event_id"] for e in events)
    assert any(n > 1 for n in ids.values()), (
        "no duplicate emitted — the dedup test would be vacuous"
    )


def test_defects_can_be_switched_off(small):
    clean = GeneratorConfig(
        events_per_day=small.events_per_day,
        missing_buy_rate_share=0.0,
        duplicate_share=0.0,
    )
    events = list(generate_day(DAY, clean))
    assert all(e["buy_rate_eur_per_min"] is not None for e in events)
    assert len(set(e["event_id"] for e in events)) == len(events)


# --- business invariants the warehouse will assert again in SQL ---


def test_only_answered_calls_bill_time(events):
    for e in events:
        if e["disposition"] != "answered":
            assert e["billable_seconds"] == 0


def test_a_human_answer_implies_an_answered_call(events):
    for e in events:
        if e["human_answered"]:
            assert e["disposition"] == "answered"


def test_dispositions_stay_inside_the_known_set(events):
    assert set(e["disposition"] for e in events) <= set(DISPOSITIONS)


def test_rates_are_positive_and_purchase_is_below_sale(events):
    for e in events:
        assert e["sell_rate_eur_per_min"] > 0
        if e["buy_rate_eur_per_min"] is not None:
            assert 0 < e["buy_rate_eur_per_min"] < e["sell_rate_eur_per_min"]


def test_timestamps_stay_inside_their_day(events):
    for e in events:
        assert e["occurred_at"].date() == DAY


def test_generate_days_rejects_a_non_positive_range(small):
    with pytest.raises(ValueError, match="n_days"):
        list(generate_days(DAY, 0, small))
