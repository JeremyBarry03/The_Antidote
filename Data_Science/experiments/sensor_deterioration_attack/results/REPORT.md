# SensorDeteriorationAttack: frozen-model robustness

Simulated Gaussian corruption of original reported SOG and COG. Original measurements are references, not independently verified physical truth. Sigma settings are experimental, not measured real-world failure rates.

SOG = max(0, original + Gaussian noise); no artificial upper cap. COG = (original + independent Gaussian noise) modulo 360. Existing missing/invalid values stay unchanged. Selection precedes both independent noise draws and is stable by vessel/timestamp/seed. Every row, coordinate, class, clock and crossing target is preserved.

112 April approaches / 110 vessels / 2,402 decision times. Models A, B and C loaded through artifact/hash compatibility checks. No retraining, recalibration, or new mitigation. C retains its existing guard and feature processing.

MAE weights each approach equally, averaging scenario seeds within approaches. MdAE and P95 pool absolute errors over decision/seed pairs. Changes use paired supported decisions. Coverage includes every scheduled decision; missing predictions are not scored as zero error. Values are minutes to the analytical reference crossing, not docking.

| Setting | Mode | Selected fraction | Model | MAE | MdAE | Δ MAE | Δ MdAE | P95 | Coverage |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| original | none | 0% | A | 7.3169 | 4.9187 | +0.0000 | +0.0000 | 23.4782 | 100.00% |
| original | none | 0% | B | 6.2989 | 2.5565 | +0.0000 | +0.0000 | 21.8750 | 100.00% |
| original | none | 0% | C | 5.8598 | 2.8070 | +0.0000 | +0.0000 | 22.1674 | 100.00% |
| low | both | 100% | A | 7.7434 | 5.3259 | +0.4265 | +0.4072 | 25.1692 | 100.00% |
| low | both | 100% | B | 6.6237 | 2.9045 | +0.3248 | +0.3480 | 22.2963 | 100.00% |
| low | both | 100% | C | 5.8941 | 2.9526 | +0.0343 | +0.1456 | 22.6752 | 100.00% |
| medium | both | 100% | A | 9.1483 | 6.5931 | +1.8315 | +1.6744 | 28.3094 | 100.00% |
| medium | both | 100% | B | 8.3951 | 3.6526 | +2.0962 | +1.0961 | 25.7144 | 100.00% |
| medium | both | 100% | C | 6.7167 | 3.4808 | +0.8569 | +0.6737 | 23.9728 | 100.00% |
| high | both | 100% | A | 13.3137 | 9.7378 | +5.9968 | +4.8191 | 40.4840 | 100.00% |
| high | both | 100% | B | 14.9967 | 5.0916 | +8.6978 | +2.5351 | 36.9521 | 100.00% |
| high | both | 100% | C | 9.7191 | 4.8685 | +3.8593 | +2.0615 | 33.7524 | 100.00% |
| extreme | both | 100% | A | 24.7152 | 17.2787 | +17.3984 | +12.3600 | 76.7740 | 100.00% |
| extreme | both | 100% | B | 39.8907 | 9.0707 | +33.5919 | +6.5142 | 253.0293 | 100.00% |
| extreme | both | 100% | C | 20.7740 | 8.3792 | +14.9143 | +5.5722 | 96.4884 | 100.00% |

Low = 0.5 kn / 2°; Medium = 1 kn / 5°; High = 2 kn / 10°; Extreme = 4 kn / 20°. Sigma zero disables a measurement. Default completed matrix: all four severities, combined mode, 100% of eligible reports, seeds 4201–4203. These vary corruption, not training. Actual selected fraction can differ in partial-selection runs because selection uses independent identity hashes.

Per-seed results, full predictions and separate report audit are locally ignored CSVs. Summary CSV includes 1,000-draw paired vessel-cluster bootstrap intervals for MAE changes. Labels/audit truth never enter predictor feature lists. Source/model hashes are checked before and after.

April was previously inspected; this is a follow-up robustness experiment, not a pristine holdout. Noise may worsen, improve or leave individual forecasts unchanged. These results do not establish naturally occurring sensor failures in the source data.

Completed 12 attacked configurations; 93,678 model forecasts including originals. Protected hashes unchanged: True.

Reproduce from Data_Science: `python experiments/sensor_deterioration_attack/run.py`.
Optional expanded matrix: `--modes sog cog both --fractions 0.1 0.25 0.5 1`. Use `--output` to preserve the default report.
