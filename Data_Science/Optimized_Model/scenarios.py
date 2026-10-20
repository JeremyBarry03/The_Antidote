"""Declared training mixtures, primary paired trials and separate volume controls."""

from .configuration import OptimizedConfig
from .replay import Condition, Scenario, seeded_generator


def training_scenarios(config: OptimizedConfig, approach_id: str, seed: int) -> list[Scenario]:
    generator = seeded_generator(seed, approach_id)
    delay = float(generator.choice(config.training_delays_minutes))
    offset = float(generator.choice(config.offsets_nautical_miles))
    fraction = float(generator.choice(config.affected_fractions))
    return [Scenario("nominal"), Scenario("stale", Condition.STALE, delay_minutes=delay),
            Scenario("quality", Condition.QUALITY, offset_nautical_miles=offset, affected_fraction=fraction),
            Scenario("combined", Condition.COMBINED, delay, offset, fraction)]


def primary_scenarios() -> list[Scenario]:
    return [Scenario("nominal"), Scenario("stale_15", Condition.STALE, delay_minutes=15),
            Scenario("quality_0.5nm_25pct", Condition.QUALITY, offset_nautical_miles=.5, affected_fraction=.25),
            Scenario("combined_15_0.5nm_25pct", Condition.COMBINED, 15, .5, .25),
            Scenario("reserved_drift", Condition.QUALITY, offset_nautical_miles=1, affected_fraction=1, drift=True)]


def stress_scenarios(config: OptimizedConfig) -> list[Scenario]:
    scenarios = [Scenario(f"delay_{age}", Condition.STALE, delay_minutes=age)
                 for age in sorted(set(config.training_delays_minutes + [60, 1440]))]
    for offset in config.offsets_nautical_miles:
        for fraction in config.affected_fractions:
            label = f"offset_{offset}_share_{fraction}"
            scenarios.extend([
                Scenario(label, Condition.QUALITY, offset_nautical_miles=offset, affected_fraction=fraction),
                Scenario(f"combined_{label}", Condition.COMBINED, 15, offset, fraction),
            ])
    return scenarios


def volume_scenarios() -> list[Scenario]:
    scenarios = [Scenario(f"fixed_volume_share_{share}", Condition.QUALITY,
                          offset_nautical_miles=.5, affected_fraction=share)
                 for share in (.1, .25, .5)]
    scenarios.extend(Scenario(f"biased_repetition_{count}", Condition.QUALITY,
                              offset_nautical_miles=.5, affected_fraction=.25, repetition=count)
                     for count in (1, 3, 5))
    scenarios.extend(Scenario(f"nonidentical_biased_repetition_{count}", Condition.QUALITY,
                              offset_nautical_miles=.5, affected_fraction=.25, repetition=count,
                              repetition_jitter_meters=.1)
                     for count in (3, 5))
    scenarios.extend(Scenario(f"all_volume_{count}", Condition.QUALITY,
                              offset_nautical_miles=.5, affected_fraction=.25, total_repetition=count)
                     for count in (1, 3, 5))
    scenarios.extend(Scenario(f"nonidentical_all_volume_{count}", Condition.QUALITY,
                              offset_nautical_miles=.5, affected_fraction=.25,
                              total_repetition=count, repetition_jitter_meters=.1)
                     for count in (3, 5))
    scenarios.extend(Scenario(f"reference_volume_{count}", total_repetition=count) for count in (1, 3, 5))
    return scenarios
