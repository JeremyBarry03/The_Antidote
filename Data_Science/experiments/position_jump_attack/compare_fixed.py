"""Compare saved normal-distance and fixed-distance runs on identical decisions."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))

from eta_baselines.dataset import file_digest
from experiments.sensor_deterioration_attack.run import summarize


def compare(normal: Path, fixed: Path) -> tuple[pd.DataFrame, dict]:
    """Reject differences in frozen artifacts, windows, cohorts or references."""
    normal_protocol = json.loads((normal/"protocol.json").read_text(encoding="utf-8"))
    fixed_protocol = json.loads((fixed/"protocol.json").read_text(encoding="utf-8"))
    for key in ("protected_hashes","models","seeds","window_policy"):
        if normal_protocol[key] != fixed_protocol[key]:
            raise ValueError(f"Cannot pair experiments with different {key}.")
    if fixed_protocol.get("displacement_std_meters",0) != 0 or normal_protocol["displacement_std_meters"] <= 0:
        raise ValueError("Expected a fixed-distance reference and positive normal distance sigma.")
    results = pd.read_csv(normal/"predictions.csv")
    reference = pd.read_csv(fixed/"predictions.csv")
    keys = ["decision_id","system","seed","displacement_meters","affected_fraction"]
    reference = reference.loc[reference.displacement_meters.isin(results.displacement_meters.unique())
                              & reference.affected_fraction.isin(results.affected_fraction.unique())]
    metadata = ["approach_id","mmsi","decision_time","arrival_time"]
    paired = results.merge(reference[keys+metadata+["error_minutes","available"]],on=keys,
                           suffixes=("","_fixed"),validate="one_to_one",how="outer",indicator=True)
    if not paired._merge.eq("both").all():
        raise ValueError("Fixed and normal runs must contain identical decision/seed/fraction pairs.")
    for column in metadata:
        if not paired[column].equals(paired[f"{column}_fixed"]):
            raise ValueError(f"Paired references differ: {column}.")
    original = paired.scenario.eq("original")
    np.testing.assert_array_equal(paired.loc[original,"available"],paired.loc[original,"available_fixed"])
    np.testing.assert_allclose(paired.loc[original,"error_minutes"],paired.loc[original,"error_minutes_fixed"],
                               rtol=0,atol=1e-10,equal_nan=True)
    paired["original_error_minutes"] = paired.error_minutes_fixed.where(paired.available_fixed)
    paired["absolute_error_change"] = paired.error_minutes.abs()-paired.original_error_minutes.abs()
    rows = []
    for _,group in paired.loc[~original].groupby(["system","displacement_meters","affected_fraction"],sort=False):
        metrics = summarize(group)
        rows.append(dict(system=metrics["system"],affected_fraction=metrics["affected_fraction"],
            mean_meters=group.displacement_meters.iloc[0],sigma_meters=normal_protocol["displacement_std_meters"],
            fixed_mae_minutes=metrics["original_mae_minutes"],
            normal_mae_minutes=metrics["original_mae_minutes"]+metrics["mae_change_minutes"],
            fixed_mdae_minutes=metrics["original_mdae_minutes"],
            normal_mdae_minutes=metrics["original_mdae_minutes"]+metrics["mdae_change_minutes"],
            normal_minus_fixed_mae=metrics["mae_change_minutes"],
            normal_minus_fixed_mdae=metrics["mdae_change_minutes"],
            mae_change_ci_low=metrics["mae_change_ci_low"],mae_change_ci_high=metrics["mae_change_ci_high"],
            normal_coverage=metrics["coverage"],paired_predictions=metrics["paired_decisions"]))
    validation = dict(identical_protected_hashes=True,identical_cohort_schedule_and_crossing_targets=True,
        original_forecasts_match=True,paired_predictions=len(paired),
        fixed_results=str(fixed),normal_results=str(normal),
        prediction_file_hashes={name:file_digest(path/"predictions.csv") for name,path in (("fixed",fixed),("normal",normal))})
    return pd.DataFrame(rows).sort_values(["mean_meters","affected_fraction","system"]),validation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normal-results",type=Path,default=HERE/"results/normal_distance")
    parser.add_argument("--fixed-results",type=Path,default=HERE/"results")
    args = parser.parse_args()
    normal,fixed = args.normal_results.resolve(),args.fixed_results.resolve()
    summary,validation = compare(normal,fixed)
    summary.to_csv(normal/"fixed_comparison.csv",index=False)
    (normal/"fixed_comparison_validation.json").write_text(json.dumps(validation,indent=2)+"\n",encoding="utf-8")
    means = ", ".join(f"{value/1000:g}" for value in summary.mean_meters.unique())
    sigma = summary.sigma_meters.iloc[0]/1000
    lines = ["# Normal versus fixed position-jump distance", "",
        f"Simulated corruption. Each normal jump is drawn independently by report identity, with mean distance(s) {means} km and standard deviation {sigma:g} km, and one unchanged bearing per vessel. This completed comparison uses the original saved fixed-distance experiment; no models were retrained. Source/model/code hashes, window policy, schedule, seed identities and original crossing targets match. Original forecasts reproduce exactly within floating-point tolerance.", "",
        "Lower error is better. Positive deltas mean normal distances are worse than fixed distances. MAE weights approaches equally; MdAE pools absolute errors. Intervals use the existing 1,000-draw paired vessel-cluster bootstrap. Rows retain unavailable decisions for coverage; paired errors use common support. The normal run's REPORT.md separately compares against the original uncorrupted feed.", "",
        "| Selected | Model | Fixed MAE | Normal MAE | Δ MAE | Fixed MdAE | Normal MdAE | Δ MdAE | Δ MAE 95% interval |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for row in summary.itertuples():
        lines.append(f"| {row.affected_fraction:.0%} | {row.system} | {row.fixed_mae_minutes:.4f} | {row.normal_mae_minutes:.4f} | {row.normal_minus_fixed_mae:+.4f} | {row.fixed_mdae_minutes:.4f} | {row.normal_mdae_minutes:.4f} | {row.normal_minus_fixed_mdae:+.4f} | [{row.mae_change_ci_low:+.4f}, {row.mae_change_ci_high:+.4f}] |")
    lines += ["", "Distance/fraction settings are experimental stress settings, not measured failure rates. Three seeds vary corruption rather than model training. The target is an analytical crossing reference, not docking. April has been inspected previously and is not a pristine holdout.", "",
              "Reproduce: `python experiments/position_jump_attack/compare_fixed.py`."]
    (normal/"FIXED_COMPARISON.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"Validated {validation['paired_predictions']:,} paired forecasts. Report: {normal/'FIXED_COMPARISON.md'}")


if __name__ == "__main__":
    main()
