"""JSON response adapter; detection rules belong to mitigation subclasses.

The module keeps the requested spelling. Responses are current-state snapshots,
not a persistent event queue: poll with advancing clocks even without new AIS.
"""

from dataclasses import dataclass

import pandas as pd

from mitigation.gap_mitigation import GapMitigation


@dataclass(frozen=True)
class AnomalyDetector:
    gap_mitigation: GapMitigation

    def evaluate(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
                 stream_ended: bool = False) -> dict[str, object]:
        """Evaluate each MMSI separately; never read labels or attack metadata."""
        if "mmsi" not in reports or reports.mmsi.isna().any():
            raise ValueError("Reports require nonmissing MMSI identifiers.")
        # Validate even empty input and invalid clocks before grouping.
        if reports.empty:
            self.gap_mitigation.apply(reports, decision_time, stream_ended=stream_ended)
        statuses = []
        anomalies = []
        for _, vessel in reports.groupby("mmsi", sort=False):
            result = self.gap_mitigation.apply(vessel, decision_time, stream_ended=stream_ended)
            if result.mmsi is None:
                continue
            statuses.append(result.to_dict())
            if result.anomaly_detected:
                anomalies.append({"type": "reporting_gap", "mmsi": result.mmsi,
                                  "severity": "warning", "eta_reliable": False,
                                  "message": "Reports stopped during an active approach; ETA uses stale evidence.",
                                  "detected_at": result.decision_time.isoformat(),
                                  "since": result.anomaly_since.isoformat(),
                                  "silence_minutes": result.silence_minutes,
                                  "report_age_minutes": result.report_age_minutes,
                                  "timeout_minutes": result.timeout_minutes})
        return {"decision_time": pd.Timestamp(decision_time).isoformat(),
                "anomaly_detected": bool(anomalies), "anomalies": anomalies,
                "vessel_statuses": statuses, "policy": self.gap_mitigation.parameters,
                "forecast_modified": False}
