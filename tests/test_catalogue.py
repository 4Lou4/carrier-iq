"""Tests for the routing catalogue.

The catalogue is the fix for a measured failure: drawing the four parts of the
decision key independently spread traffic over their cartesian product and left the
decision mart at 1.6 attempts per slot. These tests pin the properties that make it
a routing plan rather than a product of dimensions.
"""

from collections import Counter
from datetime import date

import pytest

from carrier_iq.generator import (
    CARRIERS,
    DESTINATIONS,
    ORIGINS,
    SERVICE_TIERS,
    GeneratorConfig,
    build_catalogue,
    generate_day,
)

DAY = date(2026, 3, 2)


@pytest.fixture
def cfg():
    return GeneratorConfig(events_per_day=4_000)


def test_catalogue_is_deterministic(cfg):
    # It has to be stable across days, or every trend in the warehouse would be an
    # artefact of the routing plan being redrawn overnight.
    assert build_catalogue(cfg) == build_catalogue(cfg)


def test_catalogue_reproduces_the_observed_sparsity(cfg):
    cat = build_catalogue(cfg)
    # Reference values from the system this models: 2.2 eligible carriers per group
    # on average, 39% of groups served by a single carrier.
    assert 1.8 <= cat.mean_carriers_per_group() <= 2.6
    assert 0.20 <= cat.mono_carrier_share() <= 0.50


def test_mono_carrier_groups_exist(cfg):
    # These are not noise to be smoothed away. No decision is possible on them, so
    # they are precisely what an evaluation has to exclude from its perimeter —
    # scoring them flatters every policy, including a random one.
    cat = build_catalogue(cfg)
    assert any(len(c) == 1 for c in cat.carriers)


def test_groups_are_distinct(cfg):
    cat = build_catalogue(cfg)
    assert len(set(cat.groups)) == len(cat.groups) == cfg.n_groups


def test_group_shares_sum_to_one(cfg):
    cat = build_catalogue(cfg)
    assert abs(sum(cat.group_share) - 1.0) < 1e-9
    for shares in cat.carrier_share:
        assert abs(sum(shares) - 1.0) < 1e-9


def test_asking_for_more_groups_than_exist_is_rejected():
    ceiling = len(DESTINATIONS) * len(ORIGINS) * len(SERVICE_TIERS)
    with pytest.raises(ValueError, match="exceeds"):
        build_catalogue(GeneratorConfig(n_groups=ceiling + 1))


def test_every_event_uses_a_carrier_eligible_on_its_group(cfg):
    """The invariant that makes the traffic a routing plan.

    If an event could carry a carrier that is not eligible on its group, the
    warehouse would describe routes that the routing plan forbids — and every
    aggregate built on it would be about a system that does not exist.
    """
    cat = build_catalogue(cfg)
    eligible = {
        group: set(carriers) for group, carriers in zip(cat.groups, cat.carriers, strict=True)
    }
    for e in generate_day(DAY, cfg):
        group = (e["destination_code"], e["origin_cc"], e["service_tier"])
        assert group in eligible, f"event on a group outside the catalogue: {group}"
        assert e["carrier_code"] in eligible[group]


def test_traffic_only_touches_the_catalogue(cfg):
    cat = build_catalogue(cfg)
    seen = Counter(
        (e["destination_code"], e["origin_cc"], e["service_tier"]) for e in generate_day(DAY, cfg)
    )
    assert set(seen) <= set(cat.groups)
    # And the reference lists still bound everything.
    assert set(g[0] for g in cat.groups) <= set(DESTINATIONS)
    assert set(g[1] for g in cat.groups) <= set(ORIGINS)
    assert set(g[2] for g in cat.groups) <= set(SERVICE_TIERS)
    assert set(c for group in cat.carriers for c in group) <= set(CARRIERS)
