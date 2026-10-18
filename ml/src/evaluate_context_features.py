"""Benchmark past-only telemetry and race-context features on unseen 2026 races."""
import argparse
import json
from pathlib import Path

import pandas as pd

from evaluate_interaction_features import fit_and_evaluate
from schema import TARGET, validate_columns
from train_model import MODEL_CATEGORICAL, MODEL_NUMERIC


CONTEXT_NUMERIC = (
    'attacker_pre_brake_acceleration_kph_per_s',
    'relative_pre_brake_acceleration_kph_per_s',
    'attacker_pre_brake_throttle_pct',
    'throttle_commitment_delta_pct',
    'approach_heading_change_degrees',
    'nearby_traffic_count',
    'prior_lap_duration_delta_seconds',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    frame = pd.read_parquet(args.input)
    validate_columns(frame.columns)
    missing = sorted(set(CONTEXT_NUMERIC) - set(frame.columns))
    if missing:
        raise ValueError(f'Context dataset is missing: {", ".join(missing)}')
    frame = frame[frame['model_eligible'].fillna(True)]
    train = frame[frame['year'].isin((2023, 2024))]
    validation = frame[frame['year'] == 2025]
    test = frame[frame['year'] == 2026]
    baseline = fit_and_evaluate(train, validation, test, MODEL_NUMERIC, MODEL_CATEGORICAL)
    context = fit_and_evaluate(train, validation, test,
                               (*MODEL_NUMERIC, *CONTEXT_NUMERIC), MODEL_CATEGORICAL)
    report = {
        'protocol': {'train_years': [2023, 2024], 'validation_year': 2025,
                     'test_year': 2026, 'selection_rule':
                     'Improve PR-AUC or F1 without worsening calibrated Brier score.'},
        'context_feature_coverage': {feature: {
            'train_missing': int(train[feature].isna().sum()),
            'validation_missing': int(validation[feature].isna().sum()),
            'test_missing': int(test[feature].isna().sum())} for feature in CONTEXT_NUMERIC},
        'baseline': baseline, 'context_features': context,
        'promotion_eligible': (context['test']['brier_score'] <= baseline['test']['brier_score']
                               and (context['test']['pr_auc'] > baseline['test']['pr_auc']
                                    or context['test']['f1'] > baseline['test']['f1']))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'baseline': baseline['test'], 'context_features': context['test'],
                      'promotion_eligible': report['promotion_eligible']}, indent=2))


if __name__ == '__main__':
    main()
