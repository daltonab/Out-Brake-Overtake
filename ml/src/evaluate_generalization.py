"""Benchmark calibrated pooled-model generalization by time and unseen circuit."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from prepare_data import read_rows
from schema import TARGET, validate_columns
from train_model import (FEATURES, calibrated_probability, choose_threshold, fit_platt_scaler,
                         make_pipeline, metrics)


REGULARIZATION_VALUES = (.01, .03, .1, .3, 1., 3., 10.)


def fit_benchmark_model(train, validation):
    """Tune and calibrate without using the benchmark's held-out test rows."""
    for name, subset in [('train', train), ('validation', validation)]:
        if subset[TARGET].nunique() != 2:
            raise ValueError(f'{name} must contain both outcomes')
    tuning = []
    for c_value in REGULARIZATION_VALUES:
        candidate = make_pipeline(c_value)
        candidate.fit(train[list(FEATURES)], train[TARGET])
        probability = candidate.predict_proba(validation[list(FEATURES)])[:, 1]
        tuning.append({'c': c_value,
                       'pr_auc': float(average_precision_score(validation[TARGET], probability)),
                       'roc_auc': float(roc_auc_score(validation[TARGET], probability)),
                       'brier_score': float(brier_score_loss(validation[TARGET], probability))})
    selected = max(tuning, key=lambda row: (row['pr_auc'], -row['brier_score']))
    model = make_pipeline(selected['c'])
    model.fit(train[list(FEATURES)], train[TARGET])
    validation_raw = model.predict_proba(validation[list(FEATURES)])[:, 1]
    calibration = fit_platt_scaler(validation[TARGET].to_numpy(), validation_raw)
    validation_probability = calibrated_probability(validation_raw, calibration)
    threshold = choose_threshold(validation[TARGET].to_numpy(), validation_probability)
    return model, calibration, threshold, selected, tuning


def fit_and_evaluate(train, validation, test):
    """Tune on validation PR-AUC, calibrate there, and evaluate untouched test rows."""
    if test[TARGET].nunique() != 2:
        raise ValueError('test must contain both outcomes')
    model, calibration, threshold, selected, tuning = fit_benchmark_model(train, validation)
    test_raw = model.predict_proba(test[list(FEATURES)])[:, 1]
    test_probability = calibrated_probability(test_raw, calibration)
    return {'selected_regularization_c': selected['c'], 'tuning': tuning,
            'calibration': calibration, 'threshold': threshold,
            'split_counts': {name: {'rows': int(len(subset)), 'successes': int(subset[TARGET].sum())}
                             for name, subset in [('train', train), ('validation', validation),
                                                  ('test', test)]},
            'test': metrics(test[TARGET].to_numpy(), test_probability, threshold),
            'uncalibrated_test_brier_score': float(brier_score_loss(test[TARGET], test_raw))}


def circuit_by_meeting(input_dir):
    mapping = {}
    for year_dir in sorted(input_dir.glob('[0-9][0-9][0-9][0-9]')):
        for row in read_rows(year_dir / 'catalog/meetings'):
            circuit = row.get('circuit_short_name')
            if circuit:
                mapping[row['meeting_key']] = circuit
    return mapping


def leave_one_circuit_out(frame):
    reports = []
    for circuit in sorted(frame['circuit'].unique()):
        test = frame[frame['circuit'] == circuit]
        remaining = frame[frame['circuit'] != circuit]
        # Preserve the existing weekend-safe train/validation separation for
        # model selection, while the held-out circuit remains entirely unseen.
        train = remaining[remaining['dataset_split'] == 'train']
        validation = remaining[remaining['dataset_split'] == 'validation']
        if min(test[TARGET].nunique(), train[TARGET].nunique(), validation[TARGET].nunique()) < 2:
            reports.append({'circuit': circuit, 'rows': int(len(test)),
                            'successes': int(test[TARGET].sum()), 'skipped': 'both outcomes required'})
            continue
        result = fit_and_evaluate(train, validation, test)
        reports.append({'circuit': circuit, **result})
    completed = [row for row in reports if 'test' in row]
    return {'circuits': reports,
            'summary': {'evaluated_circuits': len(completed), 'skipped_circuits': len(reports) - len(completed),
                        'macro_test_roc_auc': float(np.mean([row['test']['roc_auc'] for row in completed])),
                        'macro_test_pr_auc': float(np.mean([row['test']['pr_auc'] for row in completed])),
                        'macro_test_brier_score': float(np.mean([row['test']['brier_score'] for row in completed])),
                        'macro_test_f1': float(np.mean([row['test']['f1'] for row in completed]))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--raw-input', type=Path, default=Path('data/openf1-pooled'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    frame = pd.read_parquet(args.input)
    validate_columns(frame.columns)
    frame = frame[frame['model_eligible'].fillna(True)].copy()
    temporal_years = {'train': (2023, 2024), 'validation': (2025,), 'test': (2026,)}
    temporal = fit_and_evaluate(*(frame[frame['year'].isin(years)]
                                  for years in temporal_years.values()))
    circuits = circuit_by_meeting(args.raw_input)
    frame['circuit'] = frame['meeting_key'].map(circuits)
    if frame['circuit'].isna().any():
        raise ValueError('Missing circuit identity for one or more model rows')
    report = {'temporal_protocol': {'train_years': [2023, 2024], 'validation_years': [2025],
                                    'test_years': [2026]},
              'temporal_evaluation': temporal,
              'leave_one_circuit_out': leave_one_circuit_out(frame)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'temporal_test': temporal['test'],
                      'circuit_summary': report['leave_one_circuit_out']['summary']}, indent=2))


if __name__ == '__main__':
    main()
