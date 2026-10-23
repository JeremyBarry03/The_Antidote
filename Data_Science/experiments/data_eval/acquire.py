"""Resumable acquisition of NOAA's 2023 daily AIS CSV broadcast points."""

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import shutil
import socket
import time
import urllib.error
import urllib.request
import zipfile

import duckdb

from eta_baselines.dataset import file_digest
from eta_baselines.observations import CSV_READ_OPTIONS

logger = logging.getLogger(__name__)
SOURCE_ROOT = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2023"
BOUNDS = (-76.6, -75.8, 36.7, 37.2)
COLUMN_MAPPING = {
    "MMSI": "mmsi", "BaseDateTime": "base_date_time", "LON": "longitude", "LAT": "latitude",
    "SOG": "sog", "COG": "cog", "Heading": "heading", "VesselName": "vessel_name",
    "IMO": "imo", "CallSign": "call_sign", "VesselType": "vessel_type", "Status": "status",
    "Length": "length", "Width": "width", "Draft": "draft", "Cargo": "cargo",
    "TransceiverClass": "transceiver",
}


def download(url: str, destination: Path, attempts: int = 4) -> None:
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=90) as response, destination.open("wb") as target:
                expected = int(response.headers.get("Content-Length", 0))
                shutil.copyfileobj(response, target, length=1024**2)
            if expected and destination.stat().st_size != expected:
                raise EOFError(f"Incomplete download: {destination}")
            return
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504):
                raise
            failure = error
        except (urllib.error.URLError, socket.timeout, ConnectionError, EOFError) as error:
            failure = error
        if attempt + 1 == attempts:
            raise RuntimeError(f"Download failed after {attempts} attempts: {url}") from failure
        logger.warning("Retrying %s after attempt %s: %s", url, attempt + 1, failure)
        time.sleep(2 ** (attempt + 1))


def extract_region(
    source_csv: Path, destination: Path, day: date, rejects_path: Path | None = None,
) -> dict[str, object]:
    """Keep original values; only normalize column names and select the region."""
    with source_csv.open(encoding="utf-8-sig", newline="") as source:
        columns = next(csv.reader(source))
    if len(columns) != len(COLUMN_MAPPING) or set(COLUMN_MAPPING) != set(columns):
        raise ValueError(f"{day}: unexpected source schema: {columns}")
    rejects_path = rejects_path or destination.with_suffix(".rejects.csv")
    with duckdb.connect(config={"threads": 1, "memory_limit": "256MB"}) as connection:
        selections = ", ".join(f'"{old}" AS "{new}"' for old, new in COLUMN_MAPPING.items())
        connection.execute(
            f"CREATE TEMP TABLE subset AS SELECT {selections} "
            f"FROM read_csv(?, columns=?, {CSV_READ_OPTIONS}, store_rejects=true) "
            "WHERE TRY_CAST(LON AS DOUBLE) BETWEEN ? AND ? "
            "AND TRY_CAST(LAT AS DOUBLE) BETWEEN ? AND ?",
            [str(source_csv), dict.fromkeys(columns, "VARCHAR"), *BOUNDS],
        )
        rejected, rejection_errors = connection.execute(
            "SELECT COUNT(DISTINCT line), COUNT(*) FROM reject_errors"
        ).fetchone()
        if rejected:
            connection.execute("COPY reject_errors TO ? (FORMAT CSV, HEADER true)", [str(rejects_path)])
            logger.warning("%s: excluded %s malformed national CSV rows; preserved in %s",
                           day, rejected, rejects_path)
        else:
            rejects_path.unlink(missing_ok=True)
        count, bad, first, last = connection.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE TRY_CAST(base_date_time AS TIMESTAMP) IS NULL "
            "OR TRY_CAST(base_date_time AS DATE) != ?), MIN(base_date_time), MAX(base_date_time) FROM subset",
            [day],
        ).fetchone()
        if bad:
            raise ValueError(f"{day}: {bad} regional rows have invalid or unexpected timestamps")
        if not count:
            raise ValueError(f"{day}: empty regional subset; refusing silent missing-day coverage")
        connection.execute("COPY subset TO ? (FORMAT CSV, HEADER true)", [str(destination)])
    return {"subset_rows": count, "minimum_time": first, "maximum_time": last,
            "source_columns": columns, "output_columns": list(COLUMN_MAPPING.values()),
            "parse_rejected_rows_national": rejected, "parse_rejection_errors": rejection_errors,
            "rejects_file": rejects_path.name if rejected else None,
            "rejects_sha256": file_digest(rejects_path) if rejected else None}


def acquire_day(day: date, directory: Path) -> dict[str, object]:
    name = f"AIS_{day:%Y_%m_%d}"
    url = f"{SOURCE_ROOT}/{name}.zip"
    subset = directory / f"{day}.csv"
    manifest_file = directory / f"{day}.json"
    if subset.exists() and manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if (manifest["url"] == url and manifest["bounds"] == list(BOUNDS)
                and manifest["output_columns"] == list(COLUMN_MAPPING.values())
                and file_digest(subset) == manifest["subset_sha256"]):
            if manifest.get("rejects_file"):
                rejects = directory / manifest["rejects_file"]
                if not rejects.is_file() or file_digest(rejects) != manifest["rejects_sha256"]:
                    raise ValueError(f"Reject provenance changed for {day}")
            return manifest
        raise ValueError(f"Existing subset/provenance changed for {day}; use a fresh output directory")
    archive = directory / f"{name}.zip.partial"
    national_csv = directory / f"{name}.csv.partial"
    temporary = subset.with_suffix(".csv.partial")
    started = time.monotonic()
    try:
        logger.info("Downloading %s", day)
        download(url, archive)
        source_bytes = archive.stat().st_size
        source_hash = file_digest(archive)
        with zipfile.ZipFile(archive) as compressed:
            entries = compressed.infolist()
            if len(entries) != 1 or Path(entries[0].filename).name != f"{name}.csv":
                raise ValueError(f"Unexpected archive members for {day}")
            if shutil.disk_usage(directory).free < entries[0].file_size + 1024**3:
                raise OSError("Insufficient free disk space to extract daily AIS CSV")
            with compressed.open(entries[0]) as source, national_csv.open("wb") as output:
                # Reading to EOF validates the ZIP entry's CRC.
                shutil.copyfileobj(source, output, length=1024**2)
        details = extract_region(national_csv, temporary, day, directory / f"{day}.rejects.csv")
        manifest = {"date": day.isoformat(), "url": url, "bounds": list(BOUNDS),
                    "source_zip_bytes": source_bytes, "source_zip_sha256": source_hash,
                    "subset_sha256": file_digest(temporary), **details,
                    "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": round(time.monotonic() - started, 2)}
        temporary.replace(subset)
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Acquired %s: %s regional reports in %.1fs", day,
                    details["subset_rows"], time.monotonic() - started)
        return manifest
    finally:
        # Only temporary files owned by this day are removed; regional subsets persist.
        for path in (archive, national_csv, temporary):
            path.unlink(missing_ok=True)


def merge_days(days: list[date], directory: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".partial")
    with temporary.open("wb") as output:
        for index, day in enumerate(days):
            with (directory / f"{day}.csv").open("rb") as source:
                if index:
                    source.readline()
                shutil.copyfileobj(source, output, length=1024**2)
    temporary.replace(destination)


def acquire(destination: Path, start: date, end: date, workers: int) -> None:
    if not (date(2023, 1, 1) <= start < end <= date(2024, 1, 1)):
        raise ValueError("Supply a nonempty interval entirely within 2023")
    if not 1 <= workers <= 8:
        raise ValueError("Workers must be between 1 and 8")
    directory = destination.parent / "daily_ais_2023"
    directory.mkdir(parents=True, exist_ok=True)
    days = [start + timedelta(days=index) for index in range((end - start).days)]
    manifests = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(acquire_day, day, directory) for day in days]
        try:
            for future in as_completed(futures):
                manifests.append(future.result())
                logger.info("Completed %s/%s days", len(manifests), len(days))
        except BaseException:
            logger.exception("Acquisition stopped; cancelling queued days while active downloads finish")
            for future in futures:
                future.cancel()
            raise
    merge_days(days, directory, destination)
    destination.with_suffix(".manifest.json").write_text(json.dumps({
        "product": "NOAA 2023 AIS broadcast-point CSV; UTC; original observed values",
        "start": start.isoformat(), "end_exclusive": end.isoformat(),
        "bounds": BOUNDS, "merged_sha256": file_digest(destination),
        "days": sorted(manifests, key=lambda item: item["date"]),
    }, indent=2), encoding="utf-8")
    logger.info("Saved verified regional source: %s", destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2023, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2024, 1, 1))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    acquire(args.output.resolve(), args.start, args.end, args.workers)


if __name__ == "__main__":
    main()
