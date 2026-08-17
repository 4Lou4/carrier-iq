"""Synthetic call-event generator.

Everything emitted here comes from a seeded generator. There is no real traffic, no
real carrier, no real tariff and no real customer anywhere in this repository.

Three properties are deliberate, because the rest of the platform exists to handle
them:

**Skew.** A handful of carriers carry almost all the traffic and a handful of
destinations almost all the volume. A generator that spread traffic evenly would
make every downstream aggregate look well-behaved and would prove nothing about the
pipeline.

**Injected defects.** A fraction of events carry no purchase rate, and a fraction
are emitted twice under the same ``event_id``. These are not bugs — they are the two
defects the dbt tests have to catch, and the reason those tests are a merge gate
rather than a dashboard. A test that cannot fail proves nothing.

**Stream stability.** Only ``random.Random.random()`` is used and every other
quantity is derived from it. A fixture whose values move when a dependency is
bumped is not a fixture.

Sparsity: a measured correction, not a design flourish
-----------------------------------------------------
The first version of this generator picked the four parts of the decision key
independently. It looked skewed and it was wrong. The decision mart aggregates to
15 min x carrier x destination x origin x tier, and independent picks spread the
traffic across the *cartesian product* of those keys — 512 254 slots holding
840 000 attempts, so **1.6 attempts per slot, median 1**. Every answer rate in the
mart was 0 or 1: noise wearing the costume of a measurement. Tripling the volume
moved that number from 1.09 to 1.6, which is how it became clear the problem was
structural rather than a matter of scale.

Real routing is not cartesian, it is **sparse**. On the system this models, only
255 decision groups were ever observed, each with 2.2 eligible carriers on average
and 39% of them served by a single carrier. So the generator now builds a fixed
:class:`RoutingCatalogue` first and draws a group from it, rather than drawing four
keys and hoping they combine into something a routing plan would contain. Same
volume, 27 782 slots instead of 512 254: **mean 30, median 15**.

The defaults are then set against that measurement rather than picked round. And
even at those defaults roughly three quarters of slots hold fewer than thirty
attempts — which is not a residual bug to tune away. It is the problem: thin slots
are the normal condition of this domain, they are why an explicit decidable
perimeter and a shrinkage estimator exist downstream, and a generator that hid them
would make the platform look better than the problem is.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

__all__ = [
    "CARRIERS",
    "DESTINATIONS",
    "ORIGINS",
    "SERVICE_TIERS",
    "DISPOSITIONS",
    "GeneratorConfig",
    "RoutingCatalogue",
    "build_catalogue",
    "generate_day",
    "generate_days",
]

# Synthetic reference data. The codes are opaque on purpose: a carrier here is
# "CR-03", never a company that exists.
CARRIERS: tuple[str, ...] = tuple(f"CR-{i:02d}" for i in range(1, 13))

# A destination is a country x network-type pair, which is how a routing decision
# is actually keyed — the same country costs a different amount on fixed and mobile.
DESTINATIONS: tuple[str, ...] = tuple(
    f"DST-{i:02d}-{kind}" for i in range(1, 11) for kind in ("FIX", "MOB")
)

# Calling-country codes. Public reference data, not customer data. The origin
# belongs in the key because some carriers price the same destination differently
# depending on where the call comes from.
ORIGINS: tuple[str, ...] = ("33", "34", "44", "49", "39", "32")

SERVICE_TIERS: tuple[str, ...] = ("economy", "standard", "premium", "critical")

DISPOSITIONS: tuple[str, ...] = ("answered", "no_answer", "busy", "failed", "congestion")


@dataclass(frozen=True)
class GeneratorConfig:
    """Knobs for the generator.

    The two defect rates are the point of this class: they are configurable so a
    test can turn them off and assert the clean case, and turn them up and assert
    that the pipeline still refuses to produce a wrong aggregate.
    """

    #: Set against the measured slot density, not picked round: at this volume over a
    #: seven-day window the mart holds ~27 800 slots at a mean of 30 attempts each.
    events_per_day: int = 120_000
    #: How many decision groups exist at all. The single most important number in this
    #: file — it, not the volume, is what decides whether the decision mart carries
    #: signal. See the module docstring on sparsity.
    n_groups: int = 24
    #: Share of events whose purchase rate is missing. The audit on the real system
    #: this is modelled on found 20.5%; the pipeline must survive that order of
    #: magnitude rather than a token 1%.
    missing_buy_rate_share: float = 0.08
    #: Share of events re-emitted verbatim, as a duplicated delivery would do.
    duplicate_share: float = 0.004
    seed: int = 20260817


@dataclass(frozen=True)
class RoutingCatalogue:
    """Which carriers are eligible on which decision group, and how busy each is.

    This is the object that makes the traffic realistic, and it is the fix for a
    measured failure rather than a design flourish. See the module docstring.
    """

    #: One entry per decision group: (destination, origin, service tier).
    groups: tuple[tuple[str, str, str], ...]
    #: Eligible carriers per group, by group index. Most groups have one or two.
    carriers: tuple[tuple[str, ...], ...]
    #: Share of total traffic each group takes. Zipf-shaped.
    group_share: tuple[float, ...]
    #: Share of a group's traffic each of its carriers takes.
    carrier_share: tuple[tuple[float, ...], ...]

    def mono_carrier_share(self) -> float:
        """Share of groups where only one carrier is eligible.

        No decision is possible on those, which is exactly the *decidable perimeter*
        problem: including them in an evaluation flatters every policy, including a
        random one.
        """
        return sum(1 for c in self.carriers if len(c) == 1) / len(self.carriers)

    def mean_carriers_per_group(self) -> float:
        return sum(len(c) for c in self.carriers) / len(self.carriers)


def _zipf_weights(n: int, alpha: float) -> list[float]:
    """Normalised Zipf weights: entry of rank *k* gets a share proportional to k^-alpha.

    This replaced a vector of ``random() ** concentration`` draws, which looked skewed
    and was not: with twelve carriers it gave the busiest one about 30% of traffic,
    where the real system had three carriers on 92%. A rank-based power law is
    deterministic, has one interpretable parameter, and hits the observed shape.
    """
    raw = [k ** (-alpha) for k in range(1, n + 1)]
    total = sum(raw)
    return [w / total for w in raw]


def _weights(n: int, rng: random.Random, concentration: float) -> list[float]:
    """A skewed, normalised weight vector from plain ``random()`` draws.

    Kept for the within-group carrier split, where the exact shape matters less than
    the fact that one route usually dominates.
    """
    raw = [rng.random() ** concentration for _ in range(n)]
    total = sum(raw)
    return [w / total for w in raw]


def _pick(items: tuple[str, ...], weights: list[float], u: float) -> str:
    """Inverse-transform sampling: turn one uniform draw into one weighted pick."""
    cumulative = 0.0
    for item, w in zip(items, weights, strict=True):
        cumulative += w
        if u < cumulative:
            return item
    return items[-1]


def _pick_index(items: tuple[int, ...], weights: list[float], u: float) -> int:
    """The same, for integer indices."""
    cumulative = 0.0
    for item, w in zip(items, weights, strict=True):
        cumulative += w
        if u < cumulative:
            return item
    return items[-1]


def _event_id(*parts: object) -> str:
    """Deterministic id, so re-running the generator re-emits the same events.

    dlt deduplicates and loads incrementally on this column, so it has to be a
    stable function of the event rather than a fresh uuid on every run.
    """
    joined = "|".join(str(p) for p in parts)
    return hashlib.sha1(joined.encode()).hexdigest()[:20]


def build_catalogue(config: GeneratorConfig | None = None) -> RoutingCatalogue:
    """Build the sparse routing catalogue: which carriers serve which group.

    Derived once from the seed, so it is stable across days — a routing plan that
    changed every night would make every trend in the warehouse meaningless.
    """
    cfg = config or GeneratorConfig()
    rng = random.Random(f"{cfg.seed}:catalogue")

    ceiling = len(DESTINATIONS) * len(ORIGINS) * len(SERVICE_TIERS)
    if cfg.n_groups > ceiling:
        raise ValueError(f"n_groups={cfg.n_groups} exceeds the {ceiling} possible combinations")

    destination_w = _zipf_weights(len(DESTINATIONS), alpha=1.6)
    origin_w = _zipf_weights(len(ORIGINS), alpha=1.2)
    tier_w = _zipf_weights(len(SERVICE_TIERS), alpha=0.8)

    groups: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    while len(groups) < cfg.n_groups:
        candidate = (
            _pick(DESTINATIONS, destination_w, rng.random()),
            _pick(ORIGINS, origin_w, rng.random()),
            _pick(SERVICE_TIERS, tier_w, rng.random()),
        )
        if candidate not in seen:
            seen.add(candidate)
            groups.append(candidate)

    # Carriers per group, shaped on the observed distribution: 39% of groups had a
    # single eligible carrier and the mean was 2.2. The mono-carrier groups are not
    # noise to be smoothed away — they are the reason a decision metric needs an
    # explicit decidable perimeter.
    carriers: list[tuple[str, ...]] = []
    carrier_share: list[tuple[float, ...]] = []
    pool = list(CARRIERS)
    for _ in groups:
        u = rng.random()
        n_eligible = 1 if u < 0.39 else 2 if u < 0.69 else 3 if u < 0.86 else 4
        rng.shuffle(pool)
        eligible = tuple(pool[:n_eligible])
        carriers.append(eligible)
        # Inside a group one route usually carries most of the traffic.
        carrier_share.append(tuple(_weights(n_eligible, rng, concentration=2.0)))

    return RoutingCatalogue(
        groups=tuple(groups),
        carriers=tuple(carriers),
        group_share=tuple(_zipf_weights(len(groups), alpha=1.1)),
        carrier_share=tuple(carrier_share),
    )


def generate_day(day: date, config: GeneratorConfig | None = None) -> Iterator[dict]:
    """Yield one day of synthetic call attempts.

    The day is folded into the seed, so any single day can be regenerated on its
    own and comes out identical — which is what makes a backfill testable.
    """
    cfg = config or GeneratorConfig()
    rng = random.Random(f"{cfg.seed}:{day.isoformat()}")
    catalogue = build_catalogue(cfg)
    group_indices = tuple(range(len(catalogue.groups)))
    group_w = list(catalogue.group_share)

    # Always UTC. A generator that emitted local time would put the last hour of
    # every day into the next one as soon as the warehouse cast it to a date.
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)

    for i in range(cfg.events_per_day):
        # Pick the decision group first, then a carrier eligible on it. Picking the
        # four key parts independently is what produced a mart with 1.6 attempts per
        # slot: it spread traffic over the cartesian product of the keys, which is
        # not a shape any routing plan has.
        g = _pick_index(group_indices, group_w, rng.random())
        destination, origin, tier = catalogue.groups[g]
        carrier = _pick(catalogue.carriers[g], list(catalogue.carrier_share[g]), rng.random())

        # Latent quality of this route, stable within the day, so that aggregates
        # carry signal instead of noise.
        route = random.Random(f"{cfg.seed}:{carrier}:{destination}")
        answer_rate = 0.12 + route.random() * 0.48
        human_share = 0.35 + route.random() * 0.55

        # Traffic follows the working day rather than a flat line.
        hour_bias = rng.random() ** 0.7
        ts = midnight + timedelta(seconds=int(hour_bias * 86_399))

        u = rng.random()
        if u < answer_rate:
            disposition = "answered"
        elif u < answer_rate + 0.30:
            disposition = "no_answer"
        elif u < answer_rate + 0.38:
            disposition = "busy"
        elif u < answer_rate + 0.44:
            disposition = "congestion"
        else:
            disposition = "failed"

        answered = disposition == "answered"
        human_answered = answered and rng.random() < human_share
        # Only a conversation with a person bills real time. A machine pickup bills
        # a few seconds, which is exactly what makes a raw answer rate misleading.
        if human_answered:
            billable_seconds = 6 + int(rng.random() ** 2 * 540)
        elif answered:
            billable_seconds = 1 + int(rng.random() * 12)
        else:
            billable_seconds = 0

        sell_rate = round(0.0040 + route.random() * 0.0180, 6)
        margin_ratio = 0.05 + rng.random() * 0.45
        buy_rate: float | None = round(sell_rate * (1 - margin_ratio), 6)
        if rng.random() < cfg.missing_buy_rate_share:
            buy_rate = None

        event = {
            "event_id": _event_id(day, i, carrier, destination, origin, tier),
            "occurred_at": ts,
            "carrier_code": carrier,
            "destination_code": destination,
            "origin_cc": origin,
            "service_tier": tier,
            "disposition": disposition,
            "human_answered": human_answered,
            "billable_seconds": billable_seconds,
            "sell_rate_eur_per_min": sell_rate,
            "buy_rate_eur_per_min": buy_rate,
        }
        yield event

        # A duplicated delivery: the same event, emitted twice. Staging has to
        # collapse it, and a dbt uniqueness test has to fail if staging stops.
        if rng.random() < cfg.duplicate_share:
            yield dict(event)


def generate_days(
    start: date, n_days: int, config: GeneratorConfig | None = None
) -> Iterator[dict]:
    """Yield ``n_days`` consecutive days, oldest first."""
    if n_days < 1:
        raise ValueError("n_days must be >= 1")
    for offset in range(n_days):
        yield from generate_day(start + timedelta(days=offset), config)
