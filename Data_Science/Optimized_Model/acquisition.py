"""Acquire compatible later-period NOAA points without retaining national archives."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import json
import logging
from pathlib import Path
import shutil
import urllib.request

import duckdb

from eta_baselines.dataset import file_digest

logger = logging.getLogger(__name__)
SOURCE_ROOT = "https://ocmgeodatastor1.blob.core.windows.net/marinecadastre/ais2024"
EXTRACTION_BOUNDS = (-76.6, -75.8, 36.7, 37.2)


def _acquire_day(day: date, directory: Path) -> dict[str, object]:
    name = f"ais-{day.isoformat()}.parquet"
    url = f"{SOURCE_ROOT}/{name}"
    national = directory / f"{name}.partial"
    subset = directory / f"{day.isoformat()}.csv"
    manifest_file = directory / f"{day.isoformat()}.json"
    if subset.exists() and manifest_file.exists():
        manifest = json.loads(manifest_file.read_text())
        if file_digest(subset) == manifest["subset_sha256"]:
            return manifest
    try:
        with urllib.request.urlopen(url, timeout=90) as response, national.open("wb") as destination:
            expected = int(response.headers.get("Content-Length", 0))
            shutil.copyfileobj(response, destination, length=1024 * 1024)
        if expected and national.stat().st_size != expected:
            raise ValueError(f"Incomplete download for {day}: expected {expected} bytes.")
        with duckdb.connect() as connection:
            connection.execute("LOAD spatial")
            connection.execute(
                """CREATE TEMP TABLE subset AS SELECT mmsi, base_date_time,
                   ST_X(geometry) longitude, ST_Y(geometry) latitude,
                   sog, cog, vessel_type FROM read_parquet(?)
                   WHERE ST_X(geometry) BETWEEN ? AND ? AND ST_Y(geometry) BETWEEN ? AND ?""",
                [str(national), *EXTRACTION_BOUNDS],
            )
            count, bad = connection.execute(
                "SELECT count(*),count(*) FILTER(WHERE base_date_time::DATE != ?) FROM subset", [day],
            ).fetchone()
            if bad:
                raise ValueError(f"{day}: {bad} source timestamps have unexpected dates.")
            connection.execute("COPY subset TO ? (FORMAT CSV, HEADER true)", [str(subset)])
        manifest = {"date": day.isoformat(), "url": url, "source_bytes": national.stat().st_size,
                    "source_sha256": file_digest(national), "subset_rows": count,
                    "subset_sha256": file_digest(subset), "bounds": EXTRACTION_BOUNDS}
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Acquired %s: %s Hampton Roads observations", day, count)
        return manifest
    finally:
        national.unlink(missing_ok=True)


def acquire_later_data(destination: Path, start: str, end_exclusive: str) -> None:
    """Resumable daily subsets, strict date coverage, then one atomic merged CSV."""
    first, end = date.fromisoformat(start), date.fromisoformat(end_exclusive)
    if first >= end or first.year != 2024 or (end - timedelta(days=1)).year != 2024:
        raise ValueError("Acquisition supports a nonempty interval within the documented 2024 product.")
    directory = destination.parent / "daily_ais_subsets"
    directory.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute("INSTALL spatial")
    days = [first + timedelta(days=index) for index in range((end - first).days)]
    manifests = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_acquire_day, day, directory) for day in days]
        for future in as_completed(futures):
            manifests.append(future.result())
    temporary = destination.with_suffix(".csv.partial")
    with temporary.open("wb") as output:
        for index, day in enumerate(days):
            with (directory / f"{day}.csv").open("rb") as source:
                if index:
                    source.readline()
                shutil.copyfileobj(source, output)
    temporary.replace(destination)
    destination.with_suffix(".manifest.json").write_text(json.dumps({
        "days": sorted(manifests, key=lambda entry: entry["date"]),
        "retrieved_date": date.today().isoformat(), "merged_sha256": file_digest(destination),
        "product": "NOAA 2024 cleaned broadcast-point GeoParquet; UTC",
    }, indent=2), encoding="utf-8")
