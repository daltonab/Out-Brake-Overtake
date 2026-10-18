"""Benchmark physical and circuit-type interaction features on unseen 2026 races."""
import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from prepare_data import read_rows
from schema import TARGET, validate_columns
from train_model import (MODEL_CATEGORICAL, MODEL_NUMERIC, calibrated_probability,
                         choose_threshold, fit_platt_scaler, make_pipeline, metrics)


REGULARIZATION_VALUES = (.01, .03, .1, .3, 1., 3., 10.)


def circuit_types_by_meeting(raw_input):
    return {row['meeting_key']: row.get('circuit_type')
            for year_dir in raw_input.glob('[0-9][0-9][0-9][0-9]')
            for row in read_rows(year_dir / 'catalog/meetings')}


def enrich(frame, circuit_types):
    frame = frame.copy()
    frame['circuit_type'] = frame['meeting_key'].map(circuit_types).fillna('Unknown')
    frame['gap_speed_delta_interaction'] = frame['gap_seconds'] * frame['speed_delta_kph']
    frame['gap_brake_distance_interaction'] = frame['gap_seconds'] * frame['brake_distance_delta_m']
    for circuit_type, name in [('Temporary - Street', 'street'), ('Temporary - Road', 'road')]:
        frame[f'{name}_brake_distance_interaction'] = (
            frame['brake_distance_delta_m'] * (frame['circuit_type'] == circuit_type))
    return frame


def fit_and_evaluate(train, validation, test, numeric_features, categorical_features):
    features = [*numeric_features, *categorical_features]
    tuning = []
    for c_value in REGULARIZATION_VALUES:
        candidate = make_pipeline(c_value, numeric_features, categorical_features)
        candidate.fit(train[features], train[TARGET])
        probability = candidate.predict_proba(validation[features])[:, 1]
        tuning.append({'c': c_value,
                       'pr_auc': float(average_precision_score(validation[TARGET], probability)),
                       'roc_auc': float(roc_auc_score(validation[TARGET], probability)),
                       'brier_score': float(brier_score_loss(validation[TARGET], probability))})
    selected = max(tuning, key=lambda row: (row['pr_auc'], -row['brier_score']))
    model = make_pipeline(selected['c'], numeric_features, categorical_features)
    model.fit(train[features], train[TARGET])
    validation_raw = model.predict_proba(validation[features])[:, 1]
    calibration = fit_platt_scaler(validation[TARGET].to_numpy(), validation_raw)
    threshold = choose_threshold(validation[TARGET].to_numpy(),
                                 calibrated_probability(validation_raw, calibration))
    test_raw = model.predict_proba(test[features])[:, 1]
    test_probability = calibrated_probability(test_raw, calibration)
    return {'features': {'numeric': list(numeric_features), 'categorical': list(categorical_features)},
            'selected_regularization_c': selected['c'], 'tuning': tuning,
            'calibration': calibration, 'threshold': threshold,
            'test': metrics(test[TARGET].to_numpy(), test_probability, threshold),
            'uncalibrated_test_brier_score': float(brier_score_loss(test[TARGET], test_raw))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--raw-input', type=Path, default=Path('data/openf1-pooled'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    frame = pd.read_parquet(args.input)
    validate_columns(frame.columns)
    frame = enrich(frame[frame['model_eligible'].fillna(True)], circuit_types_by_meeting(args.raw_input))
    train = frame[frame['year'].isin((2023, 2024))]
    validation = frame[frame['year'] == 2025]
    test = frame[frame['year'] == 2026]
    interaction_features = ('gap_speed_delta_interaction', 'gap_brake_distance_interaction')
    circuit_interactions = ('street_brake_distance_interaction', 'road_brake_distance_interaction')
    experiments = {
        'baseline': fit_and_evaluate(train, validation, test, MODEL_NUMERIC, MODEL_CATEGORICAL),
        'physical_interactions': fit_and_evaluate(
            train, validation, test, (*MODEL_NUMERIC, *interaction_features), MODEL_CATEGORICAL),
        'physical_and_circuit_interactions': fit_and_evaluate(
            train, validation, test, (*MODEL_NUMERIC, *interaction_features, *circuit_interactions),
            (*MODEL_CATEGORICAL, 'circuit_type')),
    }
    baseline = experiments['baseline']['test']
    report = {'protocol': {'train_years': [2023, 2024], 'validation_year': 2025,
                           'test_year': 2026, 'selection_rule':
                           'Improve PR-AUC or F1 without worsening calibrated Brier score.'},
              'experiments': experiments,
              'promotion_eligible': {
                  name: (result['test']['brier_score'] <= baseline['brier_score']
                         and (result['test']['pr_auc'] > baseline['pr_auc']
                              or result['test']['f1'] > baseline['f1']))
                  for name, result in experiments.items() if name != 'baseline'}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'baseline': baseline,
                      'physical_interactions': experiments['physical_interactions']['test'],
                      'physical_and_circuit_interactions':
                      experiments['physical_and_circuit_interactions']['test'],
                      'promotion_eligible': report['promotion_eligible']}, indent=2))


if __name__ == '__main__':
    main()
