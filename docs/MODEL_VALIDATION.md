# Model validation record

This document records the modeling choices and benchmark outcomes behind the
published browser artifact. It is a retrospective prediction model for
historical, out-braking overtaking attempts; it is not a causal model of race
strategy or driving behaviour.

## Published model

The browser uses the `pooled-out-braking` artifact: a class-balanced logistic
regression trained on all drivers in completed 2023--2026 Race and Sprint
sessions. Its 15 pre-attempt inputs are 12 numeric signals (gap, closing rate,
speed, braking, tyre-age, race-progress, and weather measures) and three
categorical signals (both tyre compounds and attacker DRS state). Driver
identity is intentionally excluded so the baseline can generalize across the
field.

The model pipeline median-imputes and standardizes numeric fields, imputes and
one-hot encodes categorical fields, tunes L2 regularization by validation
PR-AUC, and chooses a decision threshold by validation F1. Because
class-balanced training distorts raw probabilities, a Platt scaler is fitted
only to validation predictions and applied to the exported browser model.

On the original grouped holdout split, calibration reduced Brier score from
0.0648 to 0.0422 and changed F1 from 0.7725 to 0.7759. The published artifact
therefore reports calibrated probabilities and its calibrated threshold. These
figures describe the frozen artifact and are not a guarantee of future race
performance.

## Generalization protocol

The primary robustness check is temporal: train on 2023--2024, tune and
calibrate on 2025, then confirm on 2026. This prevents a row from a later
season influencing the fitted model. A leave-one-circuit-out check also trains
without each circuit in turn. These benchmarks use the same pre-attempt fields
as the published baseline and remain separate from the browser export.

Temporal 2026 confirmation for the baseline contained 608 attempts and 114
successes:

| Metric | Result |
| --- | ---: |
| ROC-AUC | 0.9296 |
| PR-AUC | 0.7718 |
| Brier score | 0.0767 |
| Precision | 0.7404 |
| Recall | 0.6754 |
| F1 | 0.7064 |

The 26-circuit leave-one-circuit-out macro averages were ROC-AUC 0.9509,
PR-AUC 0.8301, Brier 0.0440, and F1 0.7675. Circuit macro averages and the
temporal result answer different questions; neither should be interpreted as a
claim of autonomous-strategy readiness.

## Experimental signals and promotion decisions

All feature experiments use only information observed at or before braking
onset. They are benchmark-only and are not included in the published artifact.
An experiment is eligible only when it improves the specified validation
criterion without worsening calibrated Brier score; it must then perform at
least as well on its confirmation data.

| Experiment | 2026 PR-AUC | 2026 Brier | 2026 F1 | Decision |
| --- | ---: | ---: | ---: | --- |
| Baseline | 0.7718 | 0.0767 | 0.7064 | Reference |
| Physical interactions | 0.7612 | 0.0799 | 0.7085 | Rejected |
| Physical + circuit interactions | 0.7549 | 0.0805 | 0.6887 | Rejected |
| Past-only telemetry/context bundle | 0.7159 | 0.0809 | 0.6667 | Rejected |
| Powertrain + position bundle | 0.7766 | 0.0750 | 0.7059 | Not promoted |

The last bundle includes RPM, gear, race position, and prior-lap speed-trap
difference. It produced a small ranking and calibration improvement, but F1
was effectively unchanged. The extra complexity is therefore not justified for
the browser model without stronger evidence.

## Interpretation and limits

PR-AUC is appropriate because successful attempts are uncommon. It measures
whether successful attempts are ranked above failures; Brier score measures
probability quality; F1, precision, and recall depend on the selected action
threshold. No single metric establishes operational safety.

The 2026 season was inspected during several completed experiments. It is no
longer an untouched source for further feature-selection decisions. Future
selection should use rolling historical splits and reserve subsequently
acquired seasons for independent confirmation. A production strategy system
would additionally require live-input validation, distribution-shift
monitoring, uncertainty/defer rules, a causal decision layer, and human review.

## Reproducing the checks

The commands for rebuilding the pooled dataset, training/exporting the browser
artifact, assessing calibration, and running each benchmark are in
[`ml/README.md`](../ml/README.md). Raw OpenF1-derived records, Parquet files,
binary model files, and generated JSON reports are deliberately ignored by Git;
they must be generated locally from the documented pipeline.
