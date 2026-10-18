"""Explain 2026 errors from the strict temporal pooled-model benchmark."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from evaluate_generalization import fit_benchmark_model
from prepare_data import read_rows
from schema import TARGET, validate_columns
from train_model import FEATURES, calibrated_probability, metrics


def segment_summary(frame, field):
    rows = []
    for value, group in frame.groupby(field, dropna=False, observed=True):
        tp = int(((group['prediction'] == 1) & (group[TARGET] == 1)).sum())
        fp = int(((group['prediction'] == 1) & (group[TARGET] == 0)).sum())
        fn = int(((group['prediction'] == 0) & (group[TARGET] == 1)).sum())
        tn = int(((group['prediction'] == 0) & (group[TARGET] == 0)).sum())
        rows.append({'segment': str(value), 'rows': int(len(group)),
                     'successes': int(group[TARGET].sum()),
                     'mean_predicted_probability': float(group['probability'].mean()),
                     'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                     'error_rate': float((fp + fn) / len(group)),
                     'false_positive_rate': float(fp / (tp + fp)) if tp + fp else None,
                     'false_negative_rate': float(fn / (tp + fn)) if tp + fn else None})
    return sorted(rows, key=lambda row: (-row['rows'], row['segment']))


def add_segments(frame, circuit_types):
    frame = frame.copy()
    frame['circuit_type'] = frame['meeting_key'].map(circuit_types).fillna('Unknown')
    frame['drs_state'] = np.where(frame['attacker_drs_active'], 'DRS active', 'DRS inactive')
    frame['track_condition'] = np.where(frame['rainfall'].fillna(0) > 0, 'Wet', 'Dry')
    frame['tyre_age_delta'] = frame['attacker_tyre_age_laps'] - frame['defender_tyre_age_laps']
    frame['tyre_age_delta_band'] = pd.cut(frame['tyre_age_delta'],
                                          [-np.inf, -5, -1, 1, 5, np.inf],
                                          labels=['<-5', '-5 to -1', '-1 to 1', '1 to 5', '>5'])
    frame['gap_band'] = pd.cut(frame['gap_seconds'], [-np.inf, .1, .25, .5, 1, np.inf],
                               labels=['<=0.10s', '0.10–0.25s', '0.25–0.50s', '0.50–1.00s', '>1.00s'])
    frame['speed_delta_band'] = pd.cut(frame['speed_delta_kph'],
                                       [-np.inf, 10, 20, 40, np.inf],
                                       labels=['<=10', '10–20', '20–40', '>40'])
    frame['brake_distance_band'] = pd.cut(frame['brake_distance_delta_m'],
                                          [-np.inf, 0, 10, 25, np.inf],
                                          labels=['<=0m', '0–10m', '10–25m', '>25m'])
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--raw-input', type=Path, default=Path('data/openf1-pooled'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    frame = pd.read_parquet(args.input)
    validate_columns(frame.columns)
    frame = frame[frame['model_eligible'].fillna(True)].copy()
    train = frame[frame['year'].isin((2023, 2024))]
    validation = frame[frame['year'] == 2025]
    test = frame[frame['year'] == 2026].copy()
    model, calibration, threshold, selected, tuning = fit_benchmark_model(train, validation)
    raw_probability = model.predict_proba(test[list(FEATURES)])[:, 1]
    test['probability'] = calibrated_probability(raw_probability, calibration)
    test['prediction'] = (test['probability'] >= threshold).astype(int)
    test['error_type'] = np.select(
        [(test[TARGET] == 1) & (test['prediction'] == 1),
         (test[TARGET] == 0) & (test['prediction'] == 1),
         (test[TARGET] == 1) & (test['prediction'] == 0)],
        ['true_positive', 'false_positive', 'false_negative'], default='true_negative')
    circuit_types = {}
    for year_dir in args.raw_input.glob('[0-9][0-9][0-9][0-9]'):
        for row in read_rows(year_dir / 'catalog/meetings'):
            circuit_types[row['meeting_key']] = row.get('circuit_type')
    test = add_segments(test, circuit_types)
    segments = {field: segment_summary(test, field) for field in (
        'circuit_type', 'drs_state', 'track_condition', 'tyre_age_delta_band',
        'gap_band', 'speed_delta_band', 'brake_distance_band')}
    overview = metrics(test[TARGET].to_numpy(), test['probability'].to_numpy(), threshold)
    report = {'protocol': {'train_years': [2023, 2024], 'validation_year': 2025,
                           'test_year': 2026, 'calibration': calibration,
                           'selected_regularization_c': selected['c'], 'threshold': threshold},
              'overview': overview,
              'error_counts': {label: int((test['error_type'] == label).sum())
                               for label in ('true_positive', 'false_positive',
                                             'false_negative', 'true_negative')},
              'segments': segments}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'overview': overview, 'error_counts': report['error_counts']}, indent=2))


if __name__ == '__main__':
    main()
