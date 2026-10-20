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
trains the all-driver baseline: weekend-level grouped splits, imputation, scaling,
one-hot encoding, balanced logistic regression, and
ROC-AUC/average-precision/Brier evaluation.

`src/prepare_pooled.py` is the production preparation path. It builds all-driver
attempt rows from completed race/Sprint downloads. `src/prepare_data.py` is the
shared per-driver extraction implementation used internally by that workflow.

## Training and export

`train_model.py` tunes regularization using validation PR-AUC, selects the
decision threshold using validation F1, evaluates the untouched test split and
reports results by year. `export_model.py` converts the fitted transformations,
coefficients, intercept, threshold and evaluation metadata to browser JSON.

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/train_model.py \
  --input data/processed/pooled/attempts.parquet \
  --model-output ml/models/out-braking.joblib \
  --report-output ml/reports/out-braking-model.json \
  --model-name out-braking

PYTHONPATH=ml/src .venv/bin/python ml/src/export_model.py \
  --model ml/models/out-braking.joblib \
  --output public/models/out-braking.json \
  --model-name out-braking
```

After every rebuild, run the integrity and calibration assessment before
using the model in the UI:

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/assess_model.py \
  --input data/processed/pooled/attempts.parquet \
  --model ml/models/out-braking.joblib \
  --output ml/reports/out-braking-assessment.json
```

## Generalization benchmarks

Run these benchmark-only checks before replacing the browser model. Each
individual experiment trains on 2023–2024, tunes and Platt-calibrates on 2025,
then evaluates 2026. The report also performs leave-one-circuit-out evaluation
using the existing weekend-safe training and validation partitions. Because
2026 has now informed several completed experiments, do not reuse it for new
feature selection; use rolling historical splits and reserve newly acquired
data for the next independent confirmation. See
[`docs/MODEL_VALIDATION.md`](../docs/MODEL_VALIDATION.md) for recorded results
and promotion decisions.

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/evaluate_generalization.py \
  --input data/processed/pooled/attempts.parquet \
  --output ml/reports/out-braking-generalization.json
```

For an error breakdown of the temporal test by circuit type and physical
attempt segments, run:

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/analyze_temporal_errors.py \
  --input data/processed/pooled/attempts.parquet \
  --output ml/reports/out-braking-temporal-errors.json
```

To compare proposed physical and circuit-type interaction features against the
baseline without changing the browser model, run:

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/evaluate_interaction_features.py \
  --input data/processed/pooled/attempts.parquet \
  --output ml/reports/out-braking-interactions.json
```

To benchmark past-only telemetry and race-context features, first build a
separate experimental dataset, then compare it to the baseline:

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/prepare_pooled.py \
  --output data/processed/pooled/attempts-context.parquet \
  --report ml/reports/pooled-context-preprocessing.json

PYTHONPATH=ml/src .venv/bin/python ml/src/evaluate_context_features.py \
  --input data/processed/pooled/attempts-context.parquet \
  --output ml/reports/out-braking-context.json
```

To select new powertrain, position, tyre-matchup, and session-context signals
on 2025 before one 2026 confirmation test, build a separate signal dataset and
run:

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/prepare_pooled.py \
  --output data/processed/pooled/attempts-signals.parquet \
  --report ml/reports/pooled-signals-preprocessing.json

PYTHONPATH=ml/src .venv/bin/python ml/src/evaluate_new_signals.py \
  --input data/processed/pooled/attempts-signals.parquet \
  --output ml/reports/out-braking-new-signals.json
```

## Feature-importance audit

To rank the 14 deployed inputs before simplifying the model, use descriptive
standardized coefficients together with drop-column importance. For every
input, the audit removes it, retunes regularization, recalibrates, and measures
the held-out change in PR-AUC, Brier score, and F1. Positive reported drops
mean that removal harmed performance. It uses only 2023--2025: a 2024 holdout
and a 2025 holdout. It deliberately excludes 2026 from feature selection.

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/rank_feature_importance.py \
  --input data/processed/pooled/attempts.parquet \
  --output ml/reports/out-braking-feature-importance.json
```

## Lean-model benchmark

To compare pre-defined lean feature bundles with the 14-input model, run the
non-inferiority benchmark below. A lean candidate must remain within 0.005
PR-AUC, 0.002 Brier score, and 0.01 F1 of the full model on both 2024 and 2025
holdouts. It selects the smallest qualifying candidate and deliberately does
not use 2026.

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/evaluate_lean_models.py \
  --input data/processed/pooled/attempts.parquet \
  --output ml/reports/out-braking-lean-models.json
```
