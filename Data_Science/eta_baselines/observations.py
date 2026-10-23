"""Read the large source once, selecting the declared cargo/tanker cohort."""

import logging
from pathlib import Path
from collections import Counter
from collections.abc import Iterator

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = (
    "mmsi", "base_date_time", "longitude", "latitude", "sog", "cog", "vessel_type",
)
NUMERIC_COLUMNS = ("longitude", "latitude", "sog", "cog", "vessel_type")
CSV_READ_OPTIONS = """all_varchar=true, header=true, delim=',', quote='"', escape='"'"""


def _clean_observations(observations: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Clean a complete vessel history so conflicting keys cannot straddle batches."""
    observations = observations.copy()
    audit = {"cargo_tanker_rows": len(observations)}
    observations["time"] = pd.to_datetime(
        observations.pop("base_date_time"), errors="coerce", format="mixed",
    )
    for column in NUMERIC_COLUMNS:
        observations[column] = pd.to_numeric(observations[column], errors="coerce")
    valid = (observations["mmsi"].notna() & observations["time"].notna()
             & observations["longitude"].between(-180, 180)
             & observations["latitude"].between(-90, 90))
    audit["invalid_identity_time_position_rows"] = int((~valid).sum())
    observations = observations.loc[valid].copy()
    before = len(observations)
    observations = observations.drop_duplicates()
    audit["exact_duplicate_rows_removed"] = before - len(observations)
    conflicting = observations.duplicated(["mmsi", "time"], keep=False)
    audit["conflicting_key_rows_removed"] = int(conflicting.sum())
    observations = observations.loc[~conflicting].copy()
    for column, upper_bound in (("sog", 102.2), ("cog", 359.9)):
        invalid = observations[column].notna() & ~observations[column].between(0, upper_bound)
        audit[f"invalid_{column}_replaced_with_missing"] = int(invalid.sum())
        observations.loc[invalid, column] = float("nan")
    observations = observations.sort_values(["mmsi", "time"]).reset_index(drop=True)
    return observations, audit


def iter_observation_vessels(
    path: Path, *, chunk_vectors: int = 32,
) -> Iterator[tuple[pd.DataFrame, dict[str, int]]]:
    """Stream complete MMSI histories with bounded SQL memory and per-vessel audits.

    Only raw MMSI ordering is needed in SQL. Timestamp parsing, deduplication,
    conflict exclusion and motion validation retain the shared pandas contract.
    A vessel is carried across fetch boundaries before any cleaning or labeling.
    """
    if chunk_vectors < 1:
        raise ValueError("chunk_vectors must be positive")
    valid_rows = 0
    with duckdb.connect(config={"threads": 1, "memory_limit": "256MB"}) as connection:
        columns = connection.execute(
            f"DESCRIBE SELECT * FROM read_csv(?, {CSV_READ_OPTIONS})", [str(path)]
        ).fetchdf()["column_name"]
        missing = set(REQUIRED_COLUMNS) - set(columns)
        if missing:
            raise ValueError(f"Missing required AIS columns: {sorted(missing)}")
        cursor = connection.execute(
            f"""SELECT mmsi, base_date_time, longitude, latitude, sog, cog, vessel_type
               FROM read_csv(?, {CSV_READ_OPTIONS})
               WHERE TRY_CAST(vessel_type AS DOUBLE) BETWEEN 70 AND 89
               ORDER BY mmsi""", [str(path)],
        )
        pending = pd.DataFrame()
        while True:
            chunk = cursor.fetch_df_chunk(chunk_vectors)
            if chunk.empty:
                break
            combined = pd.concat([pending, chunk], ignore_index=True) if len(pending) else chunk
            last = combined["mmsi"].iloc[-1]
            tail = combined["mmsi"].isna() if pd.isna(last) else combined["mmsi"].eq(last)
            pending = combined.loc[tail].copy()
            for _, vessel in combined.loc[~tail].groupby("mmsi", sort=False, dropna=False):
                cleaned, audit = _clean_observations(vessel)
                valid_rows += len(cleaned)
                yield cleaned, audit
        if len(pending):
            cleaned, audit = _clean_observations(pending)
            valid_rows += len(cleaned)
            yield cleaned, audit
    if not valid_rows:
        raise ValueError("No valid cargo/tanker observations remain after parsing.")
    logger.info("Loaded %s cohort observations", valid_rows)


def load_observations(path: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    """Load the shared clean cohort for callers that require an in-memory frame."""
    frames = []
    audit: Counter = Counter()
    for frame, counts in iter_observation_vessels(path):
        frames.append(frame)
        audit.update(counts)
    return pd.concat(frames, ignore_index=True), dict(audit)
