"""Select new pre-braking signals on 2025 before one 2026 confirmation test."""
import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from schema import TARGET, validate_columns
from train_model import (MODEL_CATEGORICAL, MODEL_NUMERIC, calibrated_probability,
                         choose_threshold, fit_platt_scaler, make_pipeline, metrics)


REGULARIZATION_VALUES = (.01, .03, .1, .3, 1., 3., 10.)
POWERTRAIN_AND_POSITION = ('attacker_engine_rpm', 'engine_rpm_delta', 'attacker_gear',
                           'gear_delta', 'attacker_race_position',
                           'prior_lap_speed_trap_delta_kph')
TYRE_AND_SESSION = ('tyre_matchup', 'session_name')


def fit_candidate(train, validation, numeric_features, categorical_features):
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
    raw_probability = model.predict_proba(validation[features])[:, 1]
    calibration = fit_platt_scaler(validation[TARGET].to_numpy(), raw_probability)
    probability = calibrated_probability(raw_probability, calibration)
    threshold = choose_threshold(validation[TARGET].to_numpy(), probability)
    result = {'features': {'numeric': list(numeric_features), 'categorical': list(categorical_features)},
              'selected_regularization_c': selected['c'], 'tuning': tuning,
              'calibration': calibration, 'threshold': threshold,
              'validation': metrics(validation[TARGET].to_numpy(), probability, threshold),
              'uncalibrated_validation_brier_score': float(brier_score_loss(validation[TARGET], raw_probability))}
    return model, result


def evaluate_test(model, candidate, test):
    features = [*candidate['features']['numeric'], *candidate['features']['categorical']]
    raw_probability = model.predict_proba(test[features])[:, 1]
    probability = calibrated_probability(raw_probability, candidate['calibration'])
    return {'test': metrics(test[TARGET].to_numpy(), probability, candidate['threshold']),
            'uncalibrated_test_brier_score': float(brier_score_loss(test[TARGET], raw_probability))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    frame = pd.read_parquet(args.input)
    validate_columns(frame.columns)
    required = {*POWERTRAIN_AND_POSITION, *TYRE_AND_SESSION}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f'Signal dataset is missing: {", ".join(missing)}')
    frame = frame[frame['model_eligible'].fillna(True)]
    train = frame[frame['year'].isin((2023, 2024))]
    validation = frame[frame['year'] == 2025]
    test = frame[frame['year'] == 2026]
    definitions = {
        'baseline': (MODEL_NUMERIC, MODEL_CATEGORICAL),
        'powertrain_and_position': ((*MODEL_NUMERIC, *POWERTRAIN_AND_POSITION), MODEL_CATEGORICAL),
        'tyre_matchup_and_session': (MODEL_NUMERIC, (*MODEL_CATEGORICAL, *TYRE_AND_SESSION)),
        'combined_new_signals': ((*MODEL_NUMERIC, *POWERTRAIN_AND_POSITION),
                                 (*MODEL_CATEGORICAL, *TYRE_AND_SESSION)),
    }
    fitted = {name: fit_candidate(train, validation, *definition)
              for name, definition in definitions.items()}
    baseline = fitted['baseline'][1]
    eligible = [name for name, (_, result) in fitted.items()
                if name != 'baseline'
                and result['validation']['pr_auc'] > baseline['validation']['pr_auc']
                and result['validation']['brier_score'] <= baseline['validation']['brier_score']]
    selected_name = max(eligible, key=lambda name: fitted[name][1]['validation']['pr_auc']) if eligible else 'baseline'
    report = {'protocol': {'train_years': [2023, 2024], 'selection_year': 2025,
                           'confirmation_year': 2026,
                           'selection_rule': 'Higher validation PR-AUC without worse calibrated Brier score.'},
              'feature_coverage': {feature: {
                  'train_missing': int(train[feature].isna().sum()),
                  'validation_missing': int(validation[feature].isna().sum()),
                  'test_missing': int(test[feature].isna().sum())}
                  for feature in sorted(required)},
              'candidates': {name: result for name, (_, result) in fitted.items()},
              'selected_candidate': selected_name,
              'test_confirmation': evaluate_test(fitted[selected_name][0], fitted[selected_name][1], test)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'selected_candidate': selected_name,
                      'validation': fitted[selected_name][1]['validation'],
                      'test_confirmation': report['test_confirmation']}, indent=2))


if __name__ == '__main__':
    main()
