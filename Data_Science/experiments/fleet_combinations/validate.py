"""Check an experiment against the scalar prediction path used by the demo."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import run
from eta_baselines.dataset import file_digest
from Optimized_Model.fleet import poisoning_settings
from Optimized_Model.fleet_mitigations import FleetPolicy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    protocol = json.loads((args.directory / "protocol.json").read_text())
    predictions = pd.read_csv(args.directory / "predictions.csv", dtype={"mmsi": str})
    pairs = pd.read_csv(args.directory / "ranked_failures.csv")
    for path, digest in protocol["protected_hashes"].items():
        assert file_digest(Path(path)) == digest, path
    for path, digest in protocol["implementation_hashes"].items():
        source = run.SCIENCE / path
        if source == Path(run.__file__).resolve() and (args.directory / "run_snapshot.py").exists():
            source = args.directory / "run_snapshot.py"
        assert file_digest(source) == digest, path

    run.initialize(str(run.SCIENCE / "Optimized_Model/config_vessel_class_v2.json"), protocol["seed"])
    fleet = run._RUNTIME
    decisions = fleet.dataset.partition("evaluation").set_index("decision_id", drop=False)
    checks = []
    selected = {case["id"] for case in protocol["scenarios"] if case["kind"] != "pair"}
    selected.update(pairs.nlargest(1, "delta").scenario)
    selected.update(pairs.nsmallest(1, "delta").scenario)
    for case in protocol["scenarios"]:
        if case["id"] not in selected:
            continue
        candidates = pairs.loc[pairs.scenario.eq(case["id"])]
        worst = candidates.loc[candidates.delta.abs().idxmax()]
        decision = decisions.loc[worst.decision_id]
        _, stream, _ = fleet._stream(decision.approach_id, poisoning_settings(case["settings"]))
        reports = stream.loc[stream.time.le(decision.decision_time) &
                             stream.delivered_time.le(decision.decision_time)]
        values = case["settings"]
        policy = FleetPolicy(position_faults=bool(values.get("location_drift") or values.get("position_jump")),
                             noise=bool(values.get("sensor_deterioration")),
                             speed_drift=bool(values.get("sensor_drift")))
        off, _, _ = fleet._predict(reports, decision, FleetPolicy(enabled=False))
        on, _, metadata = fleet._predict(reports, decision, policy)
        for arm, scalar in (("A", off["A"]), ("B", off["B"]),
                            ("C_guard", off["C"]), ("Antidote", on["C"])):
            result = predictions.loc[predictions.scenario.eq(case["id"]) &
                                     predictions.decision_id.eq(worst.decision_id) & predictions.arm.eq(arm)]
            assert len(result) == 1
            expected = result.iloc[0]
            assert bool(expected.available) == scalar["available"]
            if scalar["available"]:
                assert np.isclose(expected.error_minutes, scalar["error"], rtol=0, atol=1e-5), (case["id"], arm)
        checks.append(dict(scenario=case["id"], decision_id=worst.decision_id,
                           scalar_errors={arm: result["error"] for arm, result in
                                          (("A", off["A"]), ("B", off["B"]),
                                           ("C_guard", off["C"]), ("Antidote", on["C"]))},
                           requires_review=metadata["requires_review"],
                           strategies=metadata["strategies"]))
    output = dict(protected_files_unchanged=True, implementation_files_unchanged=True,
                  scalar_demo_parity=True, cases_checked=len(checks),
                  forecasts_checked=4 * len(checks), tolerance_minutes=1e-5, checks=checks)
    (args.directory / "spot_checks.json").write_text(json.dumps(output, indent=2, default=str))
    print(f"Scalar demo parity confirmed for {len(checks)} cases / {4 * len(checks)} forecasts.")


if __name__ == "__main__":
    main()
