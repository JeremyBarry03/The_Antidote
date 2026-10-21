# Normal versus fixed position-jump distance

Simulated corruption. Each normal jump is drawn independently by report identity, with mean distance(s) 2 km and standard deviation 0.2 km, and one unchanged bearing per vessel. This completed comparison uses the original saved fixed-distance experiment; no models were retrained. Source/model/code hashes, window policy, schedule, seed identities and original crossing targets match. Original forecasts reproduce exactly within floating-point tolerance.

Lower error is better. Positive deltas mean normal distances are worse than fixed distances. MAE weights approaches equally; MdAE pools absolute errors. Intervals use the existing 1,000-draw paired vessel-cluster bootstrap. Rows retain unavailable decisions for coverage; paired errors use common support. The normal run's REPORT.md separately compares against the original uncorrupted feed.

| Selected | Model | Fixed MAE | Normal MAE | Δ MAE | Fixed MdAE | Normal MdAE | Δ MdAE | Δ MAE 95% interval |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 10% | A | 9.5360 | 9.5470 | +0.0110 | 6.3600 | 6.3410 | -0.0191 | [-0.0167, +0.0387] |
| 10% | B | 6.6221 | 6.6302 | +0.0081 | 2.8428 | 2.8501 | +0.0073 | [-0.0040, +0.0226] |
| 10% | C | 6.3081 | 6.2620 | -0.0461 | 3.1309 | 3.1004 | -0.0305 | [-0.0875, -0.0106] |
| 20% | A | 11.4098 | 11.4099 | +0.0001 | 7.7767 | 7.7622 | -0.0144 | [-0.0351, +0.0368] |
| 20% | B | 6.9454 | 6.9633 | +0.0178 | 3.1391 | 3.1425 | +0.0034 | [-0.0000, +0.0400] |
| 20% | C | 6.6509 | 6.6086 | -0.0423 | 3.4095 | 3.3740 | -0.0355 | [-0.1087, +0.0299] |
| 25% | A | 12.1304 | 12.1267 | -0.0037 | 8.5186 | 8.4744 | -0.0442 | [-0.0423, +0.0365] |
| 25% | B | 7.1202 | 7.1362 | +0.0161 | 3.3297 | 3.3263 | -0.0034 | [-0.0029, +0.0391] |
| 25% | C | 6.7720 | 6.7937 | +0.0218 | 3.5171 | 3.5122 | -0.0049 | [-0.0491, +0.0941] |
| 50% | A | 14.4446 | 14.4693 | +0.0246 | 11.3111 | 11.1933 | -0.1178 | [-0.0284, +0.0809] |
| 50% | B | 7.7887 | 7.8096 | +0.0209 | 4.1733 | 4.1878 | +0.0144 | [-0.0188, +0.0628] |
| 50% | C | 7.4377 | 7.4692 | +0.0315 | 4.3142 | 4.2765 | -0.0376 | [-0.0639, +0.1222] |
| 100% | A | 9.6237 | 9.9896 | +0.3659 | 7.3921 | 7.6236 | +0.2315 | [+0.2927, +0.4455] |
| 100% | B | 9.4628 | 9.5170 | +0.0542 | 5.3116 | 5.2627 | -0.0489 | [-0.0057, +0.1170] |
| 100% | C | 7.5957 | 7.5842 | -0.0115 | 4.8019 | 4.7756 | -0.0263 | [-0.0814, +0.0610] |

Distance/fraction settings are experimental stress settings, not measured failure rates. Three seeds vary corruption rather than model training. The target is an analytical crossing reference, not docking. April has been inspected previously and is not a pristine holdout.

Reproduce: `python experiments/position_jump_attack/compare_fixed.py`.
