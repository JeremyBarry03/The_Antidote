"""Protect real source values, geographic filtering and resumable provenance."""

import csv
from datetime import date
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from experiments.data_eval import acquire
from experiments.data_eval.audit import missing_report_fields


def write_points(path: Path, when: str = "2023-01-01T00:00:00") -> None:
    row = dict.fromkeys(acquire.COLUMN_MAPPING, "")
    row.update(MMSI="123456789", BaseDateTime=when, LAT="37.0", LON="-76.2",
               SOG="12.3", COG="270.0", VesselType="70", VesselName='Ship, "One"', TransceiverClass="A")
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=acquire.COLUMN_MAPPING)
        writer.writeheader()
        writer.writerow(row)
        writer.writerow({**row, "LON": "-80.0"})


def test_subset_preserves_report_values_and_matches_march_schema(tmp_path):
    source, output = tmp_path / "source.csv", tmp_path / "region.csv"
    write_points(source)
    details = acquire.extract_region(source, output, date(2023, 1, 1))
    frame = pd.read_csv(output, dtype=str, keep_default_na=False)
    assert details["subset_rows"] == 1
    assert frame.columns.tolist() == list(acquire.COLUMN_MAPPING.values())
    assert frame.iloc[0][["base_date_time", "longitude", "sog", "cog", "vessel_name"]].tolist() == [
        "2023-01-01T00:00:00", "-76.2", "12.3", "270.0", 'Ship, "One"',
    ]


def test_wrong_day_is_rejected_before_publishing_subset(tmp_path):
    source, output = tmp_path / "source.csv", tmp_path / "region.csv"
    write_points(source, "2023-01-02T00:00:00")
    with pytest.raises(ValueError, match="unexpected timestamps"):
        acquire.extract_region(source, output, date(2023, 1, 1))
    assert not output.exists()


def test_unquoted_apostrophes_are_vessel_names_not_csv_delimiters(tmp_path):
    source, output = tmp_path / "source.csv", tmp_path / "region.csv"
    write_points(source)
    text = source.read_text().replace('"Ship, ""One"""', "'80S LADY")
    source.write_text(text)
    acquire.extract_region(source, output, date(2023, 1, 1))
    frame = pd.read_csv(output, dtype=str)
    assert frame["vessel_name"].tolist() == ["'80S LADY"]


def test_malformed_rows_are_preserved_in_reject_log_without_shifting_fields(tmp_path):
    source, output = tmp_path / "source.csv", tmp_path / "region.csv"
    write_points(source)
    original = source.read_text()
    malformed = "," + original.splitlines()[1]
    source.write_text(original + malformed + "\n")
    details = acquire.extract_region(source, output, date(2023, 1, 1))
    assert details["subset_rows"] == 1
    assert details["parse_rejected_rows_national"] == 1
    rejects = pd.read_csv(tmp_path / details["rejects_file"])
    assert rejects["csv_line"].str.lstrip("\r\n").tolist() == [malformed]
    assert details["rejects_sha256"] == acquire.file_digest(tmp_path / details["rejects_file"])
    assert source.read_text() == original + malformed + "\n"


def test_day_reuses_verified_subset_and_rejects_changed_data(tmp_path, monkeypatch):
    source = tmp_path / "fixture.csv"
    write_points(source)
    downloads = []

    def fake_download(url, destination):
        downloads.append(url)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(source, "AIS_2023_01_01.csv")

    monkeypatch.setattr(acquire, "download", fake_download)
    day = date(2023, 1, 1)
    first = acquire.acquire_day(day, tmp_path)
    assert acquire.acquire_day(day, tmp_path) == first
    assert len(downloads) == 1
    assert not list(tmp_path.glob("*.partial"))
    with (tmp_path / "2023-01-01.csv").open("a") as output:
        output.write("changed")
    with pytest.raises(ValueError, match="provenance changed"):
        acquire.acquire_day(day, tmp_path)
    assert len(downloads) == 1


def test_track_endpoints_are_not_accepted_as_report_timestamps():
    assert missing_report_fields(["MMSI", "VesselType", "TrackStartTime", "TrackEndTime", "Shape"]) == [
        "base_date_time", "longitude", "latitude", "sog", "cog",
    ]
