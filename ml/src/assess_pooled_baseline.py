"""Audit pooled split integrity, calibration, and shared-gate coverage."""

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

from schema import TARGET, validate_columns
from train_model import FEATURES


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calibration(target, probability):
    edges = np.linspace(0, 1, 6)
    rows = []
    for low, high in zip(edges[:-1], edges[1:]):
        mask = ((probability >= low) & (probability < high if high < 1 else probability <= high))
        if not mask.any():
            continue
        observed = float(target[mask].mean())
        predicted = float(probability[mask].mean())
        rows.append({'range': f'{low:.1f}-{high:.1f}', 'rows': int(mask.sum()),
                     'observed_success_rate': observed, 'mean_predicted_probability': predicted,
                     'absolute_gap': abs(observed - predicted)})
    ece = sum(row['rows'] * row['absolute_gap'] for row in rows) / len(target)
    return {'brier_score': float(brier_score_loss(target, probability)),
            'expected_calibration_error_5_bins': float(ece), 'bins': rows,
            'note': 'Diagnostic only; this model is not probability-calibrated.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    frame = pd.read_parquet(args.input)
    validate_columns(frame.columns)
    frame = frame[frame['model_eligible'].fillna(True)].copy()
    expected = {'train', 'validation', 'test'}
    splits = set(frame['dataset_split'].dropna())
    if splits != expected:
        raise ValueError(f'Expected splits {sorted(expected)}, found {sorted(splits)}')
    meeting_splits = frame.groupby('meeting_key')['dataset_split'].nunique()
    leaking_meetings = [int(key) for key, count in meeting_splits.items() if count != 1]
    if leaking_meetings:
        raise ValueError(f'Meetings cross splits: {leaking_meetings}')
    split_counts = {}
    for split in sorted(expected):
        subset = frame[frame['dataset_split'] == split]
        if subset[TARGET].nunique() != 2:
            raise ValueError(f'{split} does not contain both outcomes')
        split_counts[split] = {'rows': int(len(subset)), 'successes': int(subset[TARGET].sum()),
                               'meetings': int(subset['meeting_key'].nunique())}

    artifact = joblib.load(args.model)
    input_sha256 = digest(args.input)
    model_input_sha256 = artifact.get('input_sha256')
    if model_input_sha256 is not None and model_input_sha256 != input_sha256:
        raise ValueError('Model was trained from a different parquet revision; retrain before assessment')
    test = frame[frame['dataset_split'] == 'test']
    probability = artifact['pipeline'].predict_proba(test[list(FEATURES)])[:, 1]
    successes = frame[frame[TARGET].astype(bool)]
    gate_fields = {'gap_seconds': ('<=', 1.0), 'speed_delta_kph': ('>', 0.0),
                   'brake_onset_delta_seconds': ('<=', 5.0)}
    gate_coverage = {}
    for field, (operator, bound) in gate_fields.items():
        values = successes[field]
        covered = values <= bound if operator == '<=' else values > bound
        gate_coverage[field] = {'operator': operator, 'bound': bound,
                                'successes_covered': int(covered.sum()),
                                'successes_total': int(len(successes)),
                                'minimum': float(values.min()), 'maximum': float(values.max())}

    report = {
        'dataset_sha256': input_sha256, 'model_sha256': digest(args.model),
        'model_name': artifact.get('model_name'), 'model_scope': artifact.get('model_scope'),
        'integrity': {'passed': True, 'unique_events': int(frame['event_id'].nunique()),
                      'rows': int(len(frame)), 'meeting_split_leakage': leaking_meetings,
                      'split_counts': split_counts,
                      'missing_features': {field: int(frame[field].isna().sum()) for field in FEATURES}},
        'test_calibration': calibration(test[TARGET].to_numpy(), probability),
        'confirmed_success_gate_coverage': gate_coverage,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'integrity_passed': True, 'test_calibration': report['test_calibration'],
                      'confirmed_success_gate_coverage': gate_coverage}, indent=2))


if __name__ == '__main__':
    main()
