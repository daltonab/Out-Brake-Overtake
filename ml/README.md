# Modeling decisions

For the all-driver race/Sprint workflow, see
[Pooled preprocessing](POOLED_PREPROCESSING.md). It reuses the attempt logic and
adds stable driver IDs, pit-lap exclusions, and weekend-level splits.

- Create one row per distinct overtaking attempt, not per close-following sample.
- Braking onset is the first `brake: 0 -> 1` transition sustained for at least
  two telemetry samples and preceded by at least one second without braking.
  Do not apply a minimum-speed threshold.
- Label success only when the attacking driver passes the same opponent within
  ten seconds of braking onset.
- A failure requires an attack signature: a gap within one second and closing,
  a speed advantage, and both drivers entering the same braking event.
- Exclude ambiguous continuous following rather than labeling it as failure.
- Exclude lapped traffic, pit activity, neutralized racing, missing telemetry,
  and duplicate attempts.

## Pipeline foundation

`src/schema.py` defines the model-ready row contract. `src/train_model.py`
trains the pooled baseline: weekend-level grouped splits, imputation, scaling,
one-hot encoding, balanced logistic regression, and
ROC-AUC/average-precision/Brier evaluation.

`src/prepare_pooled.py` is the production preparation path. It builds pooled
attempt rows from completed race/Sprint downloads. `src/prepare_data.py` is the
shared per-driver extraction implementation used internally by that workflow.

The prior Max-only commands and artifact remain as a historical exploratory
baseline; do not use them for future model training.

### Legacy Max baseline reference

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/prepare_data.py \
  --input data/openf1/max-verstappen/2025 --driver 1 --session 10014 \
  --output data/processed/max-verstappen-2025-session-10014.parquet
```

Audit a completed driver/year dataset before training:

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/audit_dataset.py \
  --input data/openf1/max-verstappen/2023 --driver 1 \
  --output ml/reports/max-verstappen-2023-audit.json
```

The audit reports session completeness, confident attempts, outcome balance,
ambiguous exclusions, processing errors, and missing model feature values.

## Pooled training and export

`train_model.py` tunes regularization using validation PR-AUC, selects the
decision threshold using validation F1, evaluates the untouched test split and
reports results by year. `export_model.py` converts the fitted transformations,
coefficients, intercept, threshold and evaluation metadata to browser JSON.

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/train_model.py \
  --input data/processed/pooled/attempts.parquet \
  --model-output ml/models/pooled-out-braking.joblib \
  --report-output ml/reports/pooled-out-braking-model.json \
  --model-name pooled-out-braking

PYTHONPATH=ml/src .venv/bin/python ml/src/export_model.py \
  --model ml/models/pooled-out-braking.joblib \
  --output public/models/pooled-out-braking.json \
  --model-name pooled-out-braking
```

After every pooled rebuild, run the integrity and calibration assessment before
using the model in the UI:

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/assess_pooled_baseline.py \
  --input data/processed/pooled/attempts.parquet \
  --model ml/models/pooled-out-braking.joblib \
  --output ml/reports/pooled-out-braking-assessment.json
```
