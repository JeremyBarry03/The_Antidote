"""Whole-vessel streaming must preserve key conflicts and mixed-source clocks."""

from collections import Counter

import pandas as pd
import pytest

from eta_baselines.observations import iter_observation_vessels, load_observations


def test_vessel_and_conflicting_keys_are_not_split_across_fetch_batches(tmp_path):
    count = 5000
    frame = pd.DataFrame({
        "mmsi": "123456789", "base_date_time": pd.date_range("2023-01-01", periods=count, freq="min"),
        "longitude": -76.2, "latitude": 37.0, "sog": 12.0, "cog": 270.0, "vessel_type": 70,
    })
    # Same timestamp far apart in the input: both conflicting values must be excluded.
    conflict = frame.iloc[[0]].assign(sog=13.)
    duplicate = frame.iloc[[1]]
    other = frame.iloc[[2]].assign(mmsi="987654321")
    path = tmp_path / "reports.csv"
    pd.concat([frame, conflict, duplicate, other], ignore_index=True).to_csv(path, index=False)
    batches = list(iter_observation_vessels(path, chunk_vectors=1))
    nonempty = [batch for batch, _ in batches if len(batch)]
    audit = Counter()
    for _, counts in batches:
        audit.update(counts)
    assert len(nonempty) == 2
    assert [batch["mmsi"].nunique() for batch in nonempty] == [1, 1]
    assert [len(batch) for batch in nonempty] == [count - 1, 1]
    assert audit["exact_duplicate_rows_removed"] == 1
    assert audit["conflicting_key_rows_removed"] == 2
    assert pd.Timestamp("2023-01-01") not in set(nonempty[0]["time"])


def test_december_and_march_timestamp_formats_both_survive(tmp_path):
    path = tmp_path / "reports.csv"
    pd.DataFrame({
        "mmsi": ["123456789"] * 3,
        "base_date_time": ["2023-12-15T12:00:00", "2024-03-15 12:00:00", "bad"],
        "longitude": -76.2, "latitude": 37.0, "sog": 12.0, "cog": 270.0, "vessel_type": 70,
    }).to_csv(path, index=False)
    observations, audit = load_observations(path)
    assert observations["time"].tolist() == [pd.Timestamp("2023-12-15 12:00"), pd.Timestamp("2024-03-15 12:00")]
    assert audit["invalid_identity_time_position_rows"] == 1


def test_stream_refuses_an_empty_clean_cohort(tmp_path):
    path = tmp_path / "reports.csv"
    pd.DataFrame({
        "mmsi": [None], "base_date_time": ["2023-12-15T12:00:00"],
        "longitude": -76.2, "latitude": 37.0, "sog": 12.0, "cog": 270.0, "vessel_type": 70,
    }).to_csv(path, index=False)
    with pytest.raises(ValueError, match="No valid cargo/tanker"):
        list(iter_observation_vessels(path))
