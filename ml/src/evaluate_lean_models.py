"""Compare pre-defined lean versions of the deployed model on historical holdouts.

This is a non-inferiority selection exercise, not a 2026 confirmation. Every
candidate is tuned and Platt-calibrated independently within each fold.
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from rank_feature_importance import fit_and_score
from schema import TARGET, validate_columns
from train_model import MODEL_CATEGORICAL, MODEL_NUMERIC


CORE_NUMERIC = (
    'gap_seconds',
    'brake_onset_delta_seconds',
    'brake_distance_delta_m',
    'attacker_tyre_age_laps',
    'defender_tyre_age_laps',
)
CORE_PLUS_CLOSING = (*CORE_NUMERIC, 'closing_rate_seconds_per_second')
CORE_PLUS_CONTEXT = (*CORE_PLUS_CLOSING, 'lap_fraction', 'track_temperature_c')
NUMERIC_ONLY = tuple(feature for feature in MODEL_NUMERIC if feature != 'rainfall')

# These limits are set before evaluation. They preserve ranking, probability
# quality, and thresholded performance within a practically small tolerance.
NON_INFERIORITY_LIMITS = {
    'max_pr_auc_drop': 0.005,
    'max_brier_score_increase': 0.002,
    'max_f1_drop': 0.01,
}


def candidates():
    return {
        'full_baseline': (MODEL_NUMERIC, MODEL_CATEGORICAL),
        'physical_core_5': (CORE_NUMERIC, ()),
        'physical_core_plus_closing_6': (CORE_PLUS_CLOSING, ()),
        'physical_core_plus_context_8': (CORE_PLUS_CONTEXT, ()),
        'numeric_only_11': (NUMERIC_ONLY, ()),
    }


def split_folds(frame):
    """Return the historical folds also used for individual feature ranking."""
    return {
        '2024_holdout': (
            frame[(frame['year'] == 2023) & (frame['dataset_split'] == 'train')],
            frame[(frame['year'] == 2023) & (frame['dataset_split'] == 'validation')],
            frame[frame['year'] == 2024],
        ),
        '2025_holdout': (
            frame[frame['year'] == 2023],
            frame[frame['year'] == 2024],
            frame[frame['year'] == 2025],
        ),
    }


def difference(baseline, candidate):
    return {
        'pr_auc_drop': baseline['pr_auc'] - candidate['pr_auc'],
        'brier_score_increase': candidate['brier_score'] - baseline['brier_score'],
        'f1_drop': baseline['f1'] - candidate['f1'],
    }


def is_non_inferior(delta):
    return (delta['pr_auc_drop'] <= NON_INFERIORITY_LIMITS['max_pr_auc_drop']
            and delta['brier_score_increase'] <= NON_INFERIORITY_LIMITS['max_brier_score_increase']
            and delta['f1_drop'] <= NON_INFERIORITY_LIMITS['max_f1_drop'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    frame = pd.read_parquet(args.input)
    validate_columns(frame.columns)
    frame = frame[frame['model_eligible'].fillna(True)].copy()
    results = {}
    for candidate_name, (numeric, categorical) in candidates().items():
        fold_results = {}
        for fold_name, (train, validation, test) in split_folds(frame).items():
            fitted = fit_and_score(train, validation, test, numeric, categorical)
            fold_results[fold_name] = fitted['test']
        results[candidate_name] = {
            'numeric_features': list(numeric),
            'categorical_features': list(categorical),
            'input_count': len(numeric) + len(categorical),
            'holdouts': fold_results,
        }

    baseline = results['full_baseline']
    eligible = []
    for name, candidate in results.items():
        candidate['comparison_to_full'] = {
            fold_name: difference(baseline['holdouts'][fold_name], metrics)
            for fold_name, metrics in candidate['holdouts'].items()
        }
        candidate['non_inferior_on_each_holdout'] = all(
            is_non_inferior(delta) for delta in candidate['comparison_to_full'].values())
        if name != 'full_baseline' and candidate['non_inferior_on_each_holdout']:
            eligible.append(name)
    selected = min(eligible, key=lambda name: (results[name]['input_count'], name)) if eligible else None
    report = {
        'purpose': ('Compare pre-defined, simpler feature sets without using 2026; '
                    'a candidate must be non-inferior on both historical holdouts.'),
        'protocol': {
            'selection_data': '2023-2025 only; 2026 is excluded.',
            'holdouts': {
                '2024_holdout': 'Train/calibrate on distinct meeting-safe 2023 partitions; test on 2024.',
                '2025_holdout': 'Train on 2023; tune/calibrate on 2024; test on 2025.',
            },
            'non_inferiority_limits': NON_INFERIORITY_LIMITS,
            'selection_rule': 'Choose the smallest candidate that meets every limit on both holdouts.',
        },
        'candidates': results,
        'selected_candidate': selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'selected_candidate': selected, 'candidates': results}, indent=2))


if __name__ == '__main__':
    main()
