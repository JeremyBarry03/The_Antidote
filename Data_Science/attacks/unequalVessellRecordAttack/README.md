# UnequalVessellRecordAttack

Unequal record volume is a representation problem: heavily recorded vessels can
contribute more training loss than sparsely recorded vessels. High counts alone
do not establish corrupt data, malicious behavior, or worse ETA predictions.

This deterministic **training-time simulation** repeats the prepared examples of
the top `vessel_fraction` of training vessels by existing example count. Ties are
broken by MMSI; the selected count is rounded up. `record_multiplier=5` means five
total copies of each selected example, including its original. Neither values nor
labels change. It amplifies existing imbalance without selecting on model errors.

The attack runs after ordinary report cleaning, feature extraction and temporal
splitting. It represents oversampling or disproportionate ingestion into a
training table. It does not simulate additional independent AIS measurements.
Duplicating raw reports before the existing deduplication would be a different
experiment and would normally be removed. Evaluation records are never repeated.

```python
from attacks import UnequalVessellRecordAttack, UnequalVessellRecordConfig

attack = UnequalVessellRecordAttack(UnequalVessellRecordConfig(
    record_multiplier=5,
    vessel_fraction=.2,
))
result = attack.apply(training_examples)  # requires split='train'
# Train on result.examples using explicit feature/target column lists.
# result.modification_log and result.vessel_summary are evaluator-only audit.
```

Inputs are copied. Configuration accepts multipliers 1–100 and fractions in
`(0, 1]`. Only rows explicitly labeled `split='train'` are accepted. The result
has the original training schema; replica identifiers remain in the audit.
The attack has `name`, `stage`, `parameters`, and `apply`. It does not inherit
`BaseAttack`, whose return contract is specifically a delivered report stream.

The actual training pipeline already weights approaches equally. This bounds
the supervised influence of long approaches, although it does not equalize
vessels with different numbers of approaches. Its imputer/scaler also use
unweighted rows, and the mean-one weight convention changes total ridge loss
weight with table size. Equal approach weighting therefore need not make the
entire fitting pipeline invariant to replication.

Run the isolated A/B experiment from `Data_Science`:

```powershell
python experiments/unequal_vessell_record_attack/run.py
python -m pytest tests/test_unequal_vessell_record_attack.py -q
```

The experiment uses the original training/validation split, fixed existing model
settings and seed, and unchanged April evaluation cases. It compares current
approach weighting with a separate row-weighted counterfactual, each with its own
unamplified reference. All models and results stay inside the experiment folder;
deployed artifacts and frontend code are untouched. This attack requires
retraining and is not an instantaneous report-replay toggle.
