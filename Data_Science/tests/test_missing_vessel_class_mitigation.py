"""Class recovery uses only consistent, recent, same-vessel received evidence."""

from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from eta_baselines.configuration import FeatureConfig, GateConfig
from mitigation import BaseMitigation
from mitigation.missing_vessel_class_mitigation import (
    MissingVesselClassMitigation, MissingVesselClassMitigationConfig, VesselClassStatus,
)
from mitigation.missing_vessel_class_mitigation.optimized_model import CLASS_FEATURES, vessel_class_snapshot
from Optimized_Model.configuration import GuardConfig
from Optimized_Model.features import OptimizedFeatures


@pytest.fixture
def mitigation():
    return MissingVesselClassMitigation()


@pytest.fixture
def reports():
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-09 12:00", periods=5, freq="min"),
        "vessel_type": [70., 71., 79., np.nan, np.nan], "latitude": 37., "longitude": -76.2,
        "sog": 0., "cog": np.nan})


@pytest.fixture
def extractor():
    gate = GateConfig(-76.3, 36.95, 37.05, -75.8, 36.9, 37.1, 120, 6)
    return OptimizedFeatures(SimpleNamespace(gate=gate, features=FeatureConfig(10, 5, 10)),
                             GuardConfig(60, 60, 500, 300))


def test_recovers_broad_class_without_inventing_ais_subtype(mitigation, reports):
    before = reports.copy(deep=True)
    result = mitigation.apply(reports, "2024-04-09 12:05")
    assert isinstance(mitigation, BaseMitigation)
    assert result.status == VesselClassStatus.RECOVERED and result.recovered_class == "cargo"
    assert result.original_type is None and result.evidence_count == 3
    assert result.evidence_time == reports.time.iloc[2] and result.classification_age_minutes == 3
    assert result.observation_time == reports.time.max() and result.report_age_minutes == 1
    pd.testing.assert_frame_equal(reports, before)
    json.dumps(result.to_dict(), allow_nan=False)
    json.dumps(mitigation.parameters, allow_nan=False)


def test_recovers_tanker_and_never_defaults_zero_to_cargo(mitigation, reports):
    reports = reports.assign(vessel_type=[80., 81., 89., 0., 0.])
    result = mitigation.apply(reports, reports.time.max())
    assert result.recovered_class == "tanker" and result.original_type == 0
    assert mitigation.apply(reports.assign(vessel_type=0.), reports.time.max()).status == VesselClassStatus.UNKNOWN


@pytest.mark.parametrize("code", [70., 79., 80., 89.])
def test_observed_supported_class_is_not_overridden(mitigation, reports, code):
    reports.loc[reports.index[-1], "vessel_type"] = code
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == VesselClassStatus.OBSERVED and result.original_type == code
    assert result.recovered_class is None


@pytest.mark.parametrize("code", [30., 60., 99.])
def test_known_other_vessel_type_is_not_overridden_by_old_cargo(mitigation, reports, code):
    reports.loc[reports.index[-1], "vessel_type"] = code
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == VesselClassStatus.UNKNOWN and result.recovered_class is None
    assert "known_unsupported_class" in result.reasons


def test_conflicting_recent_history_and_current_timestamp_are_unknown(mitigation, reports):
    reports.loc[reports.index[1], "vessel_type"] = 80.
    assert "conflicting_class_history" in mitigation.apply(reports, reports.time.max()).reasons
    same_time = pd.concat([reports, reports.tail(1).assign(vessel_type=70.), reports.tail(1).assign(vessel_type=80.)])
    assert "conflicting_current_class" in mitigation.apply(same_time, reports.time.max()).reasons


def test_recent_known_other_class_blocks_recovery(mitigation, reports):
    reports.loc[reports.index[0], "vessel_type"] = 60.
    assert "conflicting_class_history" in mitigation.apply(reports, reports.time.max()).reasons


def test_no_history_insufficient_history_and_expired_history_stay_unknown(mitigation, reports):
    assert mitigation.apply(reports.assign(vessel_type=np.nan), reports.time.max()).status == VesselClassStatus.UNKNOWN
    assert mitigation.apply(reports.iloc[1:], reports.time.max()).status == VesselClassStatus.UNKNOWN
    assert mitigation.apply(reports, "2024-04-09 13:00").status == VesselClassStatus.RECOVERED
    assert mitigation.apply(reports, "2024-04-09 13:00:01").status == VesselClassStatus.UNKNOWN


def test_duplicate_reports_do_not_create_confirmations(mitigation, reports):
    one = reports.iloc[[0, 3, 4]]
    repeated = pd.concat([one, one, one]).sort_values("time")
    assert mitigation.apply(repeated, reports.time.max()).status == VesselClassStatus.UNKNOWN
    expected = mitigation.apply(reports, reports.time.max())
    assert mitigation.apply(pd.concat([reports, reports]).sample(frac=1, random_state=42), reports.time.max()) == expected


def test_future_or_late_reports_and_hidden_truth_are_never_evidence(mitigation, reports):
    reports = reports.assign(vessel_type=np.nan)
    future = reports.tail(3).assign(time=pd.date_range("2024-04-09 12:10", periods=3, freq="min"), vessel_type=70.)
    hidden = pd.concat([reports, future]).assign(original_vessel_type=70, fault_applied=True, arrival_time="hidden")
    assert mitigation.apply(hidden, reports.time.max()).status == VesselClassStatus.UNKNOWN
    late = reports.assign(vessel_type=[70., 70., 70., np.nan, np.nan], delivered_time=reports.time)
    late.loc[:2, "delivered_time"] = pd.Timestamp("2024-04-09 12:20")
    assert mitigation.apply(late, reports.time.max()).status == VesselClassStatus.UNKNOWN


def test_no_cache_is_shared_between_scenarios_or_vessels(mitigation, reports):
    assert mitigation.apply(reports, reports.time.max()).status == VesselClassStatus.RECOVERED
    assert mitigation.apply(reports.assign(vessel_type=np.nan), reports.time.max()).status == VesselClassStatus.UNKNOWN
    with pytest.raises(ValueError, match="one vessel"):
        mitigation.apply(pd.concat([reports, reports.assign(mmsi="other")]), reports.time.max())


def test_metadata_only_empty_nullable_and_invalid_numeric_inputs(mitigation, reports):
    assert mitigation.apply(reports.iloc[:0], reports.time.max()).status == VesselClassStatus.NO_REPORTS
    metadata = reports[["mmsi", "time", "vessel_type"]]
    assert mitigation.apply(metadata, reports.time.max()).status == VesselClassStatus.RECOVERED
    nullable = metadata.assign(vessel_type=pd.Series([70, 70, 70, pd.NA, pd.NA], dtype="Float64"))
    assert mitigation.apply(nullable, reports.time.max()).status == VesselClassStatus.RECOVERED
    for value in (float("inf"), -1., 70.5):
        assert mitigation.apply(metadata.assign(vessel_type=value), reports.time.max()).status == VesselClassStatus.UNKNOWN
    with pytest.raises(ValueError):
        mitigation.apply(metadata.assign(vessel_type="70"), reports.time.max())


@pytest.mark.parametrize("config", [{"minimum_reports": 0}, {"minimum_reports": True},
    {"history_minutes": 0}, {"history_minutes": float("inf")}])
def test_bad_configuration_rejected(config):
    with pytest.raises(ValueError):
        MissingVesselClassMitigationConfig(**config)


def test_adapter_changes_only_three_class_flags_and_keeps_original_rows(mitigation, reports, extractor):
    before = reports.copy(deep=True)
    snapshot = vessel_class_snapshot(reports, reports.time.max(), extractor, mitigation)
    assert snapshot.original_features[list(CLASS_FEATURES)].iloc[0].tolist() == [0., 0., 1.]
    assert snapshot.mitigated_features[list(CLASS_FEATURES)].iloc[0].tolist() == [1., 0., 0.]
    for column in snapshot.original_features:
        if column not in CLASS_FEATURES:
            pd.testing.assert_series_equal(snapshot.original_features[column], snapshot.mitigated_features[column])
    pd.testing.assert_frame_equal(reports, before)
    assert not {"recovered_class", "original_vessel_type", "arrival_time"} & set(snapshot.mitigated_features)


def test_known_cold_cache_and_empty_adapters_are_identity(mitigation, reports, extractor):
    for frame in (reports.assign(vessel_type=70.), reports.assign(vessel_type=np.nan), reports.iloc[:0]):
        snapshot = vessel_class_snapshot(frame, reports.time.max(), extractor, mitigation)
        pd.testing.assert_frame_equal(snapshot.original_features, snapshot.mitigated_features)


def test_adapter_does_not_let_arbitrary_row_order_resolve_current_conflict(mitigation, reports, extractor):
    conflict = pd.concat([reports, reports.tail(1).assign(vessel_type=70.), reports.tail(1).assign(vessel_type=80.)])
    snapshot = vessel_class_snapshot(conflict, reports.time.max(), extractor, mitigation)
    assert snapshot.mitigation.status == VesselClassStatus.UNKNOWN
    assert snapshot.mitigated_features[list(CLASS_FEATURES)].iloc[0].tolist() == [0., 0., 1.]
