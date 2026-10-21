"""Validate missing-position counts and jump-and-return screening on a tiny fixture."""

import duckdb
import numpy as np
import pandas as pd

from experiments.location_quality_audit.run import audit_month


def test_audit_counts_missing_invalid_and_isolated_location_spike(tmp_path):
    source = tmp_path/"fixture.csv"
    pd.DataFrame({"mmsi": "123456789", "base_date_time": pd.date_range("2024-03-01",periods=5,freq="min"),
        "longitude": [-76.35,-75.9,-76.35,-76.1,181],
        "latitude": [36.9,36.9,36.9,np.nan,91], "sog": 0., "vessel_type": 71}).to_csv(source,index=False)
    with duckdb.connect() as connection:
        complete,motion,keys = audit_month(connection,source,"fixture",tmp_path)
    assert complete[0]["row_count"] == 5
    assert complete[0]["missing_latitude"] == 1
    assert complete[0]["unusable_coordinates"] == 1
    assert complete[0]["outside_world_bounds"] == 1
    assert motion[1]["comparable_pairs"] == 2
    assert motion[1]["pairs_over_100_knots"] == 2
    assert motion[1]["isolated_jump_and_return_candidates"] == 1
    assert keys[0]["conflicting_coordinate_keys"] == 0
    examples = pd.read_csv(tmp_path/"fixture_position_review_candidates.csv")
    assert examples.distance_meters.between(39900,40200).all()
    assert examples.loc[examples.isolated_jump_and_return,"skip_speed_knots"].eq(0).all()
