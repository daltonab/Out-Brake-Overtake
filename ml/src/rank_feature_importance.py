"""Rank deployed-model inputs using rolling, historical drop-column checks.

Coefficient magnitude is descriptive only: correlated inputs can share the
same predictive signal. The primary rank is the held-out change after one
input is removed, the pipeline is retuned, recalibrated, and re-evaluated.
2026 is intentionally excluded so it remains out of this selection exercise.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from schema import TARGET, validate_columns
from train_model import (MODEL_CATEGORICAL, MODEL_NUMERIC, calibrated_probability,
                         choose_threshold, fit_platt_scaler, make_pipeline, metrics)


REGULARIZATION_VALUES = (.01, .03, .1, .3, 1., 3., 10.)


def fit_and_score(train, validation, test, numeric_features, categorical_features):
    """Tune, calibrate, and evaluate one feature set without reading test labels."""
    features = [*numeric_features, *categorical_features]
    tuning = []
    for c_value in REGULARIZATION_VALUES:
        candidate = make_pipeline(c_value, numeric_features, categorical_features)
        candidate.fit(train[features], train[TARGET])
        raw_probability = candidate.predict_proba(validation[features])[:, 1]
        tuning.append({
            'c': c_value,
            'pr_auc': float(average_precision_score(validation[TARGET], raw_probability)),
            'roc_auc': float(roc_auc_score(validation[TARGET], raw_probability)),
            'brier_score': float(brier_score_loss(validation[TARGET], raw_probability)),
        })
    selected = max(tuning, key=lambda row: (row['pr_auc'], -row['brier_score']))
    model = make_pipeline(selected['c'], numeric_features, categorical_features)
    model.fit(train[features], train[TARGET])
    validation_raw = model.predict_proba(validation[features])[:, 1]
    calibration = fit_platt_scaler(validation[TARGET].to_numpy(), validation_raw)
    threshold = choose_threshold(
        validation[TARGET].to_numpy(), calibrated_probability(validation_raw, calibration))
    test_raw = model.predict_proba(test[features])[:, 1]
    test_probability = calibrated_probability(test_raw, calibration)
    return {
        'model': model,
        'selected_regularization_c': selected['c'],
        'calibration': calibration,
        'threshold': threshold,
        'test': metrics(test[TARGET].to_numpy(), test_probability, threshold),
    }


def coefficient_summary(model, numeric_features, categorical_features):
    """Return comparable numeric coefficients and grouped categorical strength."""
    coefficients = model.named_steps['model'].coef_[0]
    numeric_coefficients = coefficients[:len(numeric_features)]
    categorical_encoder = (model.named_steps['transform'].named_transformers_['categorical']
                           .named_steps['encode'])
    cursor = len(numeric_features)
    categorical = {}
    for feature, categories in zip(categorical_features, categorical_encoder.categories_):
        values = coefficients[cursor:cursor + len(categories)]
        categorical[feature] = {
            'l2_coefficient_strength': float(np.linalg.norm(values)),
            'max_absolute_category_coefficient': float(np.max(np.abs(values))),
            'category_coefficients': {str(category): float(value)
                                      for category, value in zip(categories, values)},
        }
        cursor += len(categories)
    return ({feature: float(value) for feature, value in zip(numeric_features, numeric_coefficients)},
            categorical)


def omitted_feature_sets(feature):
    """Return the numeric/categorical input sets with exactly one feature removed."""
    if feature in MODEL_NUMERIC:
        return tuple(item for item in MODEL_NUMERIC if item != feature), MODEL_CATEGORICAL
    return MODEL_NUMERIC, tuple(item for item in MODEL_CATEGORICAL if item != feature)


def rank_summary(rows):
    """Aggregate holdout deltas; positive values mean removing the field harmed performance."""
    result = []
    for feature in (*MODEL_NUMERIC, *MODEL_CATEGORICAL):
        feature_rows = [row for row in rows if row['feature'] == feature]
        deltas = {name: np.array([row[name] for row in feature_rows])
                  for name in ('pr_auc_drop', 'brier_score_increase', 'f1_drop')}
        result.append({
            'feature': feature,
            'kind': 'numeric' if feature in MODEL_NUMERIC else 'categorical',
            'mean_pr_auc_drop': float(deltas['pr_auc_drop'].mean()),
            'mean_brier_score_increase': float(deltas['brier_score_increase'].mean()),
            'mean_f1_drop': float(deltas['f1_drop'].mean()),
            'folds_with_pr_auc_harm': int((deltas['pr_auc_drop'] > 0).sum()),
            'folds_with_brier_harm': int((deltas['brier_score_increase'] > 0).sum()),
            'folds_with_f1_harm': int((deltas['f1_drop'] > 0).sum()),
        })
    return sorted(result, key=lambda row: (-row['mean_pr_auc_drop'],
                                            -row['mean_brier_score_increase'],
                                            -row['mean_f1_drop']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    frame = pd.read_parquet(args.input)
    validate_columns(frame.columns)
    frame = frame[frame['model_eligible'].fillna(True)].copy()
    folds = {
        # The first held-out season uses the pre-existing meeting-safe 2023
        # partition for tuning/calibration. The second is fully chronological.
        '2024_holdout': (frame[(frame['year'] == 2023) & (frame['dataset_split'] == 'train')],
                         frame[(frame['year'] == 2023) & (frame['dataset_split'] == 'validation')],
                         frame[frame['year'] == 2024]),
        '2025_holdout': (frame[frame['year'] == 2023], frame[frame['year'] == 2024],
                         frame[frame['year'] == 2025]),
    }
    all_rows, baseline_by_fold, coefficient_by_fold = [], {}, {}
    for name, (train, validation, test) in folds.items():
        baseline = fit_and_score(train, validation, test, MODEL_NUMERIC, MODEL_CATEGORICAL)
        baseline_by_fold[name] = {
            'split_counts': {label: {'rows': int(len(subset)), 'successes': int(subset[TARGET].sum())}
                             for label, subset in [('train', train), ('validation', validation),
                                                   ('test', test)]},
            'selected_regularization_c': baseline['selected_regularization_c'],
            'test': baseline['test'],
        }
        numeric, categorical = coefficient_summary(baseline['model'], MODEL_NUMERIC, MODEL_CATEGORICAL)
        coefficient_by_fold[name] = {'numeric_standardized_coefficients': numeric,
                                     'categorical_group_strength': categorical}
        for feature in (*MODEL_NUMERIC, *MODEL_CATEGORICAL):
            numeric_features, categorical_features = omitted_feature_sets(feature)
            omitted = fit_and_score(train, validation, test, numeric_features, categorical_features)
            all_rows.append({
                'fold': name,
                'feature': feature,
                'omitted_test': omitted['test'],
                'pr_auc_drop': baseline['test']['pr_auc'] - omitted['test']['pr_auc'],
                'brier_score_increase': (omitted['test']['brier_score']
                                         - baseline['test']['brier_score']),
                'f1_drop': baseline['test']['f1'] - omitted['test']['f1'],
            })
    report = {
        'purpose': ('Rank current inputs for simplification using descriptive coefficients and '
                    'held-out drop-column impact; this is not a causal-effect estimate.'),
        'protocol': {
            'selection_data': '2023-2025 only; 2026 is excluded.',
            'folds': {
                '2024_holdout': 'Train and calibrate on separate meeting-safe 2023 partitions; test on 2024.',
                '2025_holdout': 'Train on 2023; tune and calibrate on 2024; test on 2025.',
            },
            'importance_definition': ('Positive PR-AUC/F1 drops or positive Brier increases mean that '
                                      'removing a field harmed held-out performance.'),
        },
        'baseline_by_fold': baseline_by_fold,
        'coefficient_by_fold': coefficient_by_fold,
        'drop_column_by_feature_and_fold': all_rows,
        'feature_ranking': rank_summary(all_rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'feature_ranking': report['feature_ranking']}, indent=2))


if __name__ == '__main__':
    main()
