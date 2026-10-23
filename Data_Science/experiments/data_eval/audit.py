"""Audit a candidate GeoPackage against the existing AIS report contract.

Run from Data_Science with ``python -m experiments.data_eval.audit --help``.
This command reads sources without converting tracks into invented reports.
"""

import argparse
import csv
import json
import logging
from pathlib import Path
import sqlite3

from eta_baselines.observations import REQUIRED_COLUMNS

logger = logging.getLogger(__name__)


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def missing_report_fields(columns: list[str]) -> list[str]:
    """Compare spelling aliases only; endpoints are not report timestamps."""
    normalized = {column.lower().replace("_", "") for column in columns}
    return [name for name in REQUIRED_COLUMNS if name.replace("_", "") not in normalized]


def audit_geopackage(source: Path, reference_csv: Path) -> dict[str, object]:
    source = source.resolve(strict=True)
    reference_csv = reference_csv.resolve(strict=True)
    with reference_csv.open(newline="", encoding="utf-8-sig") as reference:
        reference_columns = next(csv.reader(reference))
    if missing_report_fields(reference_columns):
        raise ValueError("Reference CSV does not satisfy the AIS observation schema")
    layers = []
    # mode=ro prevents accidental writes, including creation for a mistyped path.
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        geometries = connection.execute(
            "SELECT table_name, column_name, geometry_type_name, srs_id, z, m "
            "FROM gpkg_geometry_columns ORDER BY table_name"
        ).fetchall()
        if not geometries:
            raise ValueError("GeoPackage contains no feature layers")
        for table, geometry_column, geometry_type, srs_id, z, m in geometries:
            table_sql = quote_identifier(table)
            schema = connection.execute(f"PRAGMA table_info({table_sql})").fetchall()
            columns = [row[1] for row in schema]
            logger.info("Auditing %s (%s); scanning source date ranges", table, geometry_type)
            fields = ["COUNT(*)"]
            for timestamp in ("TrackStartTime", "TrackEndTime", "base_date_time"):
                if timestamp in columns:
                    name = quote_identifier(timestamp)
                    fields.extend((f"MIN({name})", f"MAX({name})"))
            values = connection.execute(f"SELECT {', '.join(fields)} FROM {table_sql}").fetchone()
            missing = missing_report_fields(columns)
            points = geometry_type.upper() in ("POINT", "MULTIPOINT")
            layers.append({
                "table": table,
                "row_count": values[0],
                "columns": [{"name": row[1], "type": row[2]} for row in schema],
                "geometry": {"column": geometry_column, "type": geometry_type,
                             "srs_id": srs_id, "z": z, "m": m},
                "date_ranges": dict(zip(fields[1:], values[1:])),
                "missing_required_report_columns": missing,
                "has_point_geometry": points,
                "report_schema_compatible": points and not missing,
                "extent": connection.execute(
                    "SELECT min_x, min_y, max_x, max_y FROM gpkg_contents WHERE table_name=?",
                    (table,),
                ).fetchone(),
            })
    compatible = any(layer["report_schema_compatible"] for layer in layers)
    return {
        "source": str(source), "source_bytes": source.stat().st_size,
        "reference_csv": str(reference_csv), "reference_columns": reference_columns,
        "required_report_columns": list(REQUIRED_COLUMNS), "layers": layers,
        "status": "report_schema_matches" if compatible else "blocked_incompatible_training_source",
        "schema_check_scope": "Column/geometry check; not a substitute for value/date/cohort validation.",
        "requested_evaluation_period": {"start": "2024-03-01", "end_exclusive": "2024-04-01"},
        "april_2024_data_used": False,
        "training_performed": False,
        "evaluation_performed": False,
        "reason": (
            "Schema matches; validate values, dates and geographic cohort before training."
            if compatible else
            "Track endpoints and untimed line vertices do not provide individual AIS report "
            "timestamps, SOG or COG. Interpolating them would create synthetic training data "
            "and cannot reproduce the existing A/B/C observation and gate-crossing contract."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpkg", type=Path, required=True)
    parser.add_argument("--reference-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.output.resolve() in (args.gpkg.resolve(), args.reference_csv.resolve()):
        parser.error("Output must differ from both source files")
    report = audit_geopackage(args.gpkg, args.reference_csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    logger.info("%s; saved %s", report["status"], args.output)


if __name__ == "__main__":
    main()
