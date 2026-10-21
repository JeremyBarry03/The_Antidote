"""Read-only coordinate completeness and motion-consistency audit of local AIS extracts."""

import json
from pathlib import Path
import sys

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0, str(SCIENCE))

from eta_baselines.dataset import file_digest


def distance_sql(lat: str, lon: str, other_lat: str, other_lon: str) -> str:
    """Spherical great-circle distance in meters, for screening rather than surveying."""
    return f"""12742000 * asin(sqrt(least(1.,
        pow(sin(radians({lat}-{other_lat})/2),2)
        + cos(radians({lat}))*cos(radians({other_lat}))
          * pow(sin(radians({lon}-{other_lon})/2),2))))"""


def audit_month(connection: duckdb.DuckDBPyConnection, path: Path, month: str,
                output: Path) -> tuple[list[dict], list[dict], list[dict]]:
    connection.execute("""CREATE OR REPLACE TEMP TABLE raw AS SELECT
        mmsi, longitude, latitude, TRY_CAST(longitude AS DOUBLE) lon,
        TRY_CAST(latitude AS DOUBLE) lat, TRY_CAST(vessel_type AS DOUBLE) type_code,
        TRY_CAST(base_date_time AS TIMESTAMP) report_time, TRY_CAST(sog AS DOUBLE) speed
        FROM read_csv(?, all_varchar=true)""", [str(path)])
    completeness = []
    for cohort, where in (("all", "true"), ("cargo_tanker", "type_code BETWEEN 70 AND 89")):
        record = connection.execute(f"""SELECT count(*) row_count, count(DISTINCT mmsi) mmsis,
            count(*) FILTER(WHERE longitude IS NULL OR trim(longitude)='') missing_longitude,
            count(*) FILTER(WHERE latitude IS NULL OR trim(latitude)='') missing_latitude,
            count(*) FILTER(WHERE lon IS NULL OR lat IS NULL OR NOT isfinite(lon) OR NOT isfinite(lat)) unusable_coordinates,
            count(*) FILTER(WHERE isfinite(lon) AND isfinite(lat) AND
                (lon NOT BETWEEN -180 AND 180 OR lat NOT BETWEEN -90 AND 90)) outside_world_bounds,
            count(*) FILTER(WHERE lon=0 AND lat=0) zero_zero_positions,
            count(*) FILTER(WHERE lon=181 OR lat=91) unavailable_position_sentinels,
            count(*) FILTER(WHERE lon NOT BETWEEN -76.6 AND -75.8 OR lat NOT BETWEEN 36.7 AND 37.2) outside_extract_bounds,
            count(*) FILTER(WHERE report_time IS NULL) invalid_times,
            min(lon) min_longitude,max(lon) max_longitude,min(lat) min_latitude,max(lat) max_latitude
            FROM raw WHERE {where}""").fetchdf().to_dict(orient="records")[0]
        completeness.append(dict(month=month, cohort=cohort, **record))
    connection.execute("""CREATE OR REPLACE TEMP TABLE keyed AS SELECT mmsi, report_time,
        min(lon) lon, min(lat) lat, median(speed) speed, min(type_code) type_code,
        count(DISTINCT (lon,lat)) coordinate_versions, count(*) copies
        FROM raw WHERE mmsi IS NOT NULL AND report_time IS NOT NULL
        AND isfinite(lon) AND isfinite(lat) AND lon BETWEEN -180 AND 180 AND lat BETWEEN -90 AND 90
        GROUP BY mmsi,report_time""")
    key_audit = connection.execute("""SELECT count(*) unique_vessel_time_keys,
        count(*) FILTER(WHERE coordinate_versions>1) conflicting_coordinate_keys,
        sum(copies-1) extra_rows_on_keys FROM keyed""").fetchdf().to_dict(orient="records")[0]
    lagged = """SELECT *, lag(report_time) OVER w previous_time, lag(lon) OVER w previous_longitude,
        lag(lat) OVER w previous_latitude, lag(speed) OVER w previous_speed,
        lag(type_code) OVER w previous_type, lead(report_time) OVER w next_time,
        lead(lon) OVER w next_longitude, lead(lat) OVER w next_latitude,
        lead(type_code) OVER w next_type
        FROM keyed WHERE coordinate_versions=1 WINDOW w AS (PARTITION BY mmsi ORDER BY report_time)"""
    step = distance_sql("lat", "lon", "previous_latitude", "previous_longitude")
    next_step = distance_sql("lat", "lon", "next_latitude", "next_longitude")
    skip = distance_sql("previous_latitude", "previous_longitude", "next_latitude", "next_longitude")
    connection.execute(f"""CREATE OR REPLACE TEMP TABLE movements AS WITH lagged AS ({lagged}),
        distances AS (SELECT *, epoch(report_time-previous_time) elapsed_seconds,
            epoch(next_time-report_time) next_elapsed_seconds, {step} distance_meters,
            {next_step} next_distance_meters, {skip} skip_distance_meters FROM lagged)
        SELECT *, distance_meters*3600/1852/nullif(elapsed_seconds,0) implied_speed_knots,
            next_distance_meters*3600/1852/nullif(next_elapsed_seconds,0) next_implied_speed_knots,
            skip_distance_meters*3600/1852/nullif(elapsed_seconds+next_elapsed_seconds,0) skip_speed_knots,
            abs(distance_meters*3600/1852/nullif(elapsed_seconds,0)-(speed+previous_speed)/2) speed_disagreement_knots
        FROM distances""")
    motion = []
    for cohort, where in (("all", "true"),
                          ("cargo_tanker", "type_code BETWEEN 70 AND 89 AND previous_type BETWEEN 70 AND 89")):
        record = connection.execute(f"""SELECT count(*) comparable_pairs,
            count(DISTINCT mmsi) mmsis,
            count(*) FILTER(WHERE implied_speed_knots>60) pairs_over_60_knots,
            count(DISTINCT mmsi) FILTER(WHERE implied_speed_knots>60) mmsis_over_60_knots,
            count(*) FILTER(WHERE implied_speed_knots>100) pairs_over_100_knots,
            count(*) FILTER(WHERE lon=previous_longitude AND lat=previous_latitude
                AND speed BETWEEN 3 AND 102.2 AND previous_speed BETWEEN 3 AND 102.2) unchanged_position_while_reporting_motion,
            count(*) FILTER(WHERE speed BETWEEN 3 AND 102.2 AND previous_speed BETWEEN 3 AND 102.2
                AND abs(speed-previous_speed)<=2 AND speed_disagreement_knots>10) stable_sog_disagreement_over_10_knots,
            count(*) FILTER(WHERE next_elapsed_seconds BETWEEN 30 AND 300 AND implied_speed_knots>60
                AND next_implied_speed_knots>60 AND skip_speed_knots<=30
                AND ('{cohort}'='all' OR next_type BETWEEN 70 AND 89)) isolated_jump_and_return_candidates,
            max(implied_speed_knots) maximum_implied_speed_knots
            FROM movements WHERE elapsed_seconds BETWEEN 30 AND 300 AND {where}""").fetchdf().to_dict(orient="records")[0]
        motion.append(dict(month=month, cohort=cohort, **record))
    flags = connection.execute("""SELECT mmsi,previous_time,report_time,previous_longitude,previous_latitude,
        lon longitude,lat latitude,previous_speed,speed,speed_disagreement_knots,type_code,previous_type,
        elapsed_seconds,distance_meters,implied_speed_knots,next_time,next_implied_speed_knots,skip_speed_knots,
        implied_speed_knots>60 high_implied_speed,
        (lon=previous_longitude AND lat=previous_latitude AND speed BETWEEN 3 AND 102.2
            AND previous_speed BETWEEN 3 AND 102.2) unchanged_position_while_reporting_motion,
        (speed BETWEEN 3 AND 102.2 AND previous_speed BETWEEN 3 AND 102.2 AND abs(speed-previous_speed)<=2
            AND speed_disagreement_knots>10) motion_speed_disagreement,
        coalesce((next_elapsed_seconds BETWEEN 30 AND 300 AND implied_speed_knots>60
            AND next_implied_speed_knots>60 AND skip_speed_knots<=30),false) isolated_jump_and_return
        FROM movements WHERE elapsed_seconds BETWEEN 30 AND 300 AND
        (implied_speed_knots>60 OR unchanged_position_while_reporting_motion OR motion_speed_disagreement)
        ORDER BY implied_speed_knots DESC""").fetchdf()
    flags.to_csv(output/f"{month}_position_review_candidates.csv", index=False)
    connection.execute("DROP TABLE movements")
    connection.execute("DROP TABLE keyed")
    connection.execute("DROP TABLE raw")
    print(json.dumps(dict(month=month, completeness=completeness, motion=motion, keys=key_audit), indent=2), flush=True)
    return completeness, motion, [dict(month=month, **key_audit)]


def review_examples(sources: dict[str, Path], output: Path) -> dict:
    """Verify source neighborhoods and match flagged endpoints to actual model histories."""
    flags = []
    for month in sources:
        frame = pd.read_csv(output/f"{month}_position_review_candidates.csv", dtype={"mmsi": str})
        selected = frame.loc[frame.type_code.between(70,89) & frame.previous_type.between(70,89)
                             & frame.high_implied_speed].copy()
        selected["month"] = month
        for column in ("report_time", "previous_time"):
            selected[column] = pd.to_datetime(selected[column])
        flags.append(selected)
    flagged = pd.concat(flags, ignore_index=True)
    events = pd.concat([flagged[["mmsi", "report_time"]].rename(columns={"report_time": "time"}),
                        flagged[["mmsi", "previous_time"]].rename(columns={"previous_time": "time"})]).drop_duplicates()
    overlap = {"strict_jump_and_return_rows": int(flagged.isolated_jump_and_return.sum()),
               "high_speed_leg_endpoint_events": len(events), "matching_cached_approaches": []}
    from Optimized_Model.configuration import OptimizedConfig
    from Optimized_Model.dataset import load_replay

    try:
        config = OptimizedConfig.load(SCIENCE/"Optimized_Model/config_vessel_class_v2.json")
        dataset = load_replay(config)
        for key, history in dataset.histories.items():
            hits = history[["mmsi", "time"]].merge(events, on=["mmsi", "time"])
            if len(hits):
                decisions = dataset.decisions.loc[dataset.decisions.approach_id.eq(key)]
                overlap["matching_cached_approaches"].append(dict(approach_id=key,
                    mmsi=str(hits.mmsi.iloc[0]), flagged_times=hits.time.astype(str).tolist(),
                    splits=sorted(decisions.split.unique().tolist())))
        overlap["evaluation_approaches"] = int(dataset.partition("evaluation").approach_id.nunique())
        overlap["evaluation_decisions"] = len(dataset.partition("evaluation"))
        overlap["status"] = "Checked all hash-validated cached model histories, including training and evaluation."
    except (FileNotFoundError, ValueError) as error:
        overlap["status"] = f"Model-history comparison unavailable: {error}"
    with duckdb.connect() as connection:
        connection.execute("SET threads=4")
        names = connection.execute("""SELECT mmsi,string_agg(DISTINCT vessel_name,' / ') vessel_names,
            string_agg(DISTINCT vessel_type,' / ') vessel_types FROM read_csv(?,all_varchar=true)
            WHERE mmsi IN (SELECT unnest(?)) GROUP BY mmsi""",
            [str(sources["march"]), sorted(flagged.mmsi.unique().tolist())]).fetchdf()
        names.to_csv(output/"candidate_vessel_names.csv", index=False)
        contexts = []
        cases = [("march","563032900","2024-03-27 10:40:00","2024-03-27 10:52:00"),
                 ("april","563032700","2024-04-01 11:43:00","2024-04-01 11:56:00"),
                 ("april","352003673","2024-04-12 08:47:00","2024-04-12 09:00:00")]
        for month,mmsi,start,end in cases:
            fields = "mmsi,base_date_time,longitude,latitude,sog,cog,vessel_type"+(" ,vessel_name" if month == "march" else "")
            frame = connection.execute(f"""SELECT {fields} FROM read_csv(?,all_varchar=true)
                WHERE mmsi=? AND TRY_CAST(base_date_time AS TIMESTAMP)
                BETWEEN TRY_CAST(? AS TIMESTAMP) AND TRY_CAST(? AS TIMESTAMP) ORDER BY base_date_time""",
                [str(sources[month]),mmsi,start,end]).fetchdf()
            frame["month"] = month
            contexts.append(frame)
        pd.concat(contexts,ignore_index=True).to_csv(output/"original_position_jump_examples.csv",index=False)
    (output/"model_cohort_overlap.json").write_text(json.dumps(overlap,indent=2),encoding="utf-8")
    return overlap


def main() -> None:
    output = HERE/"results"
    output.mkdir(exist_ok=True)
    sources = {month: SCIENCE.parent/"data"/f"hampton_roads_{month}_2024.csv" for month in ("march", "april")}
    hashes = {month: file_digest(path) for month,path in sources.items()}
    completeness, motion, keys = [], [], []
    with duckdb.connect() as connection:
        connection.execute("SET threads=4")
        for month,path in sources.items():
            c,m,k = audit_month(connection,path,month,output)
            completeness.extend(c)
            motion.extend(m)
            keys.extend(k)
    overlap = review_examples(sources,output)
    assert hashes == {month: file_digest(path) for month,path in sources.items()}
    evidence = dict(sources={month:str(path) for month,path in sources.items()}, source_sha256=hashes,
        source_hashes_unchanged=True, completeness=completeness, motion=motion, key_audit=keys,
        model_history_overlap=overlap,
        protocol=dict(coordinate_checks="Raw CSV, before cargo filtering or model preprocessing",
            motion="Unambiguous vessel/time keys; duplicates consolidated; great-circle displacement",
            intervals_seconds=[30,300], high_speed_threshold_knots=60,
            caveat="Consistency flags are review candidates, not independently verified bad coordinates",
            provenance="Geographically filtered extracts can exclude missing or invalid coordinates upstream; absence here does not establish absence in original national broadcasts"))
    (output/"audit.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    pd.DataFrame(completeness).to_csv(output/"completeness.csv",index=False)
    pd.DataFrame(motion).to_csv(output/"motion_summary.csv",index=False)
    lines = ["# Location quality audit", "", "Read-only audit of original local March/April 2024 extracts. No attack was implemented or injected. Source hashes were checked before and after.", "",
        "| Month | Scope | Rows | Missing lon | Missing lat | Unusable coordinates | Out-of-world bounds | (0,0) |",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in completeness:
        lines.append(f"| {r['month']} | {r['cohort']} | {r['row_count']:,} | {r['missing_longitude']} | {r['missing_latitude']} | {r['unusable_coordinates']} | {r['outside_world_bounds']} | {r['zero_zero_positions']} |")
    lines += ["", "Motion checks use consecutive unambiguous vessel/time keys, 30–300 seconds apart, with spherical great-circle displacement. Cargo/tanker pairs require both endpoints to have type 70–89. An isolated jump-and-return requires both legs >60 knots but <=30 knots when the middle report is skipped. Exact repeated coordinates with endpoint SOG >=3 knots and disagreement between stable reported SOG and geometric speed are separate consistency flags.", "",
        "| Month | Scope | Compared pairs | >60 kn | >100 kn | Same position while reporting motion | Stable SOG disagreement >10 kn | Jump-and-return |",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in motion:
        lines.append(f"| {r['month']} | {r['cohort']} | {r['comparable_pairs']:,} | {r['pairs_over_60_knots']} | {r['pairs_over_100_knots']} | {r['unchanged_position_while_reporting_motion']} | {r['stable_sog_disagreement_over_10_knots']} | {r['isolated_jump_and_return_candidates']} |")
    lines += ["", "Verified original-record example: MAERSK SEOUL, MMSI 563032900, 27 March 2024 (UTC):",
        "", "| Time | Longitude | Latitude | SOG (knots) |", "|---|---:|---:|---:|",
        "| 10:44:04 | -76.35004 | 36.87790 | 0.0 |",
        "| 10:45:32 | -75.88680 | 36.89419 | 10.1 |",
        "| 10:47:05 | -76.35006 | 36.87792 | 0.0 |", "",
        "The first leg spans approximately 41.24 km in 88 seconds (910.93 knots), followed by a return near the original location 93 seconds later. This sequence cannot represent the vessel's real motion. It establishes inconsistent position/time/identity records, but does not identify whether the cause was GPS, identity collision, timing or source processing.", "",
        "Additional original examples: MMSI 563032700 on April 1 has a 42.51 km jump in 70 seconds followed by a return; MMSI 352003673 on April 12 has a 21.14 km jump in 67 seconds followed by a return. April extracts have no vessel-name column, and those MMSIs had no matching March name in this lookup.", "",
        f"Model-history cross-check: {overlap['status']} Matches among the flagged high-speed leg endpoints: {len(overlap['matching_cached_approaches'])}. Evaluation contains {overlap.get('evaluation_approaches','unavailable')} approaches and {overlap.get('evaluation_decisions','unavailable')} decisions. Zero matches means these examples cannot explain the existing model benchmark errors."]
    lines += ["", "These are consistency screens, not confirmed location errors. Either positions or SOG could be inaccurate; turns and changing speed also affect comparisons. No independent physical position truth is available.", "",
        "The available files are geographic extracts, not untouched national AIS messages. The April acquisition explicitly filters ST_X/ST_Y to longitude [-76.6,-75.8] and latitude [36.7,37.2], which excludes null/unlocatable positions. All zero counts are conditional on the local extract and cannot establish source-wide prevalence.", "",
        "There is no dedicated MissingLocationAttack in the active attacks package. Existing replay scenarios already simulate incorrect positions: quality_0.5nm_25pct shifts 25% of reports by 0.5 nautical miles (926 m); reserved_drift grows a position offset over time. These are simulated, not defects observed in the source.", "",
        "Model preprocessing currently rejects missing/invalid positions before building approaches. A future missing-location attack would need explicit handling of reports with unusable coordinates; zero-filling would invent a location. No runtime, frontend, model, attack or source data changes were made.", "",
        "CSV review candidates and summary outputs are locally ignored. Reproduce from Data_Science: `python experiments/location_quality_audit/run.py`."]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
