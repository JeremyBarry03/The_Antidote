"""Outage boundaries, source preservation, targeting, and replay causality."""

import pandas as pd
import pytest

from attacks import BaseAttack, ReportingGapAttack, ReportingGapConfig


@pytest.fixture
def reports() -> pd.DataFrame:
    return pd.DataFrame({"mmsi": "123456789",
                         "time": pd.date_range("2024-04-10 12:00", periods=7, freq="min"),
                         "longitude": [-76.10 - i * .001 for i in range(7)],
                         "latitude": 37., "sog": 12., "cog": 270., "vessel_type": 70})


@pytest.fixture
def attack() -> ReportingGapAttack:
    return ReportingGapAttack(ReportingGapConfig(pd.Timestamp("2024-04-10 12:02"),
                                               pd.Timestamp("2024-04-10 12:05")))


def test_gap_drops_start_boundary_and_resumes_at_end_without_backfill(reports, attack):
    stream = attack.apply(reports)
    assert isinstance(attack, BaseAttack)
    assert stream.reports.time.dt.minute.tolist() == [0, 1, 5, 6]
    assert stream.available(pd.Timestamp("2024-04-10 12:04")).time.dt.minute.tolist() == [0, 1]
    assert stream.available(pd.Timestamp("2024-04-10 12:06")).time.dt.minute.tolist() == [0, 1, 5, 6]
    assert stream.modification_log.loc[stream.modification_log.fault_applied, "time"].dt.minute.tolist() == [2, 3, 4]


def test_preserves_source_and_retained_measurements(reports, attack):
    original = reports.copy(deep=True)
    stream = attack.apply(reports)
    pd.testing.assert_frame_equal(reports, original)
    pd.testing.assert_frame_equal(stream.reports[reports.columns], reports.iloc[[0, 1, 5, 6]])
    assert not {"attack", "fault_applied", "action"} & set(stream.reports)


def test_targets_only_selected_mmsi(reports):
    other = reports.assign(mmsi="987654321")
    mixed = pd.concat([reports, other], ignore_index=True)
    attack = ReportingGapAttack(ReportingGapConfig(pd.Timestamp("2024-04-10 12:02"),
                                                  pd.Timestamp("2024-04-10 12:05"), "123456789"))
    stream = attack.apply(mixed)
    assert stream.reports.groupby("mmsi").size().to_dict() == {"123456789": 4, "987654321": 7}


def test_future_reports_cannot_change_earlier_available_feed(reports, attack):
    time = pd.Timestamp("2024-04-10 12:03")
    pd.testing.assert_frame_equal(attack.apply(reports).available(time),
                                  attack.apply(reports.loc[reports.time <= time]).available(time))


def test_preserves_existing_delivery_times_and_record_ids(reports, attack):
    reports = reports.assign(delivered_time=reports.time + pd.Timedelta(minutes=2),
                             record_id=[f"source-{i}" for i in range(len(reports))])
    stream = attack.apply(reports)
    assert stream.available(pd.Timestamp("2024-04-10 12:05")).record_id.tolist() == ["source-0", "source-1"]
    assert stream.reports.record_id.tolist() == ["source-0", "source-1", "source-5", "source-6"]


def test_empty_and_complete_outage_keep_replay_schema(reports):
    attack = ReportingGapAttack(ReportingGapConfig(pd.Timestamp("2024-04-10 11:00"),
                                                  pd.Timestamp("2024-04-10 13:00")))
    for source in [reports, reports.iloc[:0]]:
        stream = attack.apply(source)
        assert stream.available(pd.Timestamp("2024-04-10 12:05")).empty
        assert {"time", "delivered_time", "record_id"} <= set(stream.reports)


def test_no_overlap_is_a_noop_on_measurements(reports):
    attack = ReportingGapAttack(ReportingGapConfig(pd.Timestamp("2024-04-11"), pd.Timestamp("2024-04-12")))
    stream = attack.apply(reports)
    pd.testing.assert_frame_equal(stream.reports[reports.columns], reports)
    assert not stream.modification_log.fault_applied.any()


@pytest.mark.parametrize("start,end", [("bad", "2024-04-10"), ("NaT", "2024-04-10"),
                                      ("2024-04-10", "2024-04-10"), ("2024-04-11", "2024-04-10"),
                                      ("2024-04-10T12:00Z", "2024-04-10T13:00")])
def test_rejects_invalid_windows(start, end):
    with pytest.raises(ValueError):
        ReportingGapConfig(start, end)


@pytest.mark.parametrize("mmsi", ["", "abc", "123", 123456789])
def test_rejects_invalid_target_mmsi(mmsi):
    with pytest.raises(ValueError, match="nine-digit"):
        ReportingGapConfig(pd.Timestamp("2024-04-10"), pd.Timestamp("2024-04-11"), mmsi)


def test_accepts_aware_times_but_rejects_implicit_timezone_conversion(reports, attack):
    aware = reports.assign(time=reports.time.dt.tz_localize("UTC"))
    with pytest.raises(ValueError, match="timezones"):
        attack.apply(aware)
    config = ReportingGapConfig(pd.Timestamp("2024-04-10 12:02Z"), pd.Timestamp("2024-04-10 12:05Z"))
    assert len(ReportingGapAttack(config).apply(aware).reports) == 4


def test_rejects_missing_schema_or_unparsed_times(reports, attack):
    with pytest.raises(ValueError, match="columns"):
        attack.apply(reports.drop(columns="time"))
    with pytest.raises(ValueError, match="datetimes"):
        attack.apply(reports.assign(time=reports.time.astype(str)))
    with pytest.raises(ValueError, match="before"):
        attack.apply(reports.assign(delivered_time=reports.time-pd.Timedelta(seconds=1)))
