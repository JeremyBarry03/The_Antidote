"""Read the large source once, selecting the declared cargo/tanker cohort."""

import logging
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = (
    "mmsi", "base_date_time", "longitude", "latitude", "sog", "cog", "vessel_type",
)
NUMERIC_COLUMNS = ("longitude", "latitude", "sog", "cog", "vessel_type")


def load_observations(path: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    """Select type 70–89 records; discard conflicting timestamp keys, not guess them."""
    with duckdb.connect() as connection:
        columns = connection.execute(
            "DESCRIBE SELECT * FROM read_csv(?, all_varchar=true)", [str(path)]
        ).fetchdf()["column_name"]
        missing = set(REQUIRED_COLUMNS) - set(columns)
        if missing:
            raise ValueError(f"Missing required AIS columns: {sorted(missing)}")
        connection.execute(
            """
            CREATE TEMP TABLE cohort AS
            SELECT mmsi, base_date_time, longitude, latitude, sog, cog, vessel_type
            FROM read_csv(?, all_varchar=true)
            WHERE TRY_CAST(vessel_type AS DOUBLE) BETWEEN 70 AND 89
            """, [str(path)],
        )
        observations = connection.execute("SELECT * FROM cohort").fetchdf()
    audit = {"cargo_tanker_rows": len(observations)}
    observations["time"] = pd.to_datetime(observations.pop("base_date_time"), errors="coerce")
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
    if observations.empty:
        raise ValueError("No valid cargo/tanker observations remain after parsing.")
    logger.info("Loaded %s cohort observations", len(observations))
    return observations, audit
