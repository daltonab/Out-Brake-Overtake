"""Tune, evaluate, and save the pooled out-braking logistic-regression model."""
import argparse, hashlib, io, json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix,
                             f1_score, precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from schema import TARGET, validate_columns

MODEL_NUMERIC = ('gap_seconds', 'closing_rate_seconds_per_second', 'attacker_speed_kph',
                 'speed_delta_kph', 'brake_onset_delta_seconds', 'brake_distance_delta_m',
                 'throttle_lift_delta_seconds', 'attacker_tyre_age_laps',
                 'defender_tyre_age_laps', 'lap_fraction', 'rainfall', 'track_temperature_c')
MODEL_CATEGORICAL = ('attacker_compound', 'defender_compound', 'attacker_drs_active')
FEATURES = (*MODEL_NUMERIC, *MODEL_CATEGORICAL)


def make_pipeline(c_value):
    transform = ColumnTransformer([
        ('numeric', Pipeline([('impute', SimpleImputer(strategy='median')),
                              ('scale', StandardScaler())]), list(MODEL_NUMERIC)),
        ('categorical', Pipeline([('impute', SimpleImputer(strategy='most_frequent')),
                                  ('encode', OneHotEncoder(handle_unknown='ignore'))]),
         list(MODEL_CATEGORICAL)),
    ])
    return Pipeline([('transform', transform),
                     ('model', LogisticRegression(C=c_value, class_weight='balanced',
                                                  max_iter=5000, random_state=42))])


def metrics(target, probability, threshold):
    prediction = (probability >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(target, prediction, labels=[0, 1]).ravel()
    return {'rows': int(len(target)), 'positives': int(np.sum(target)),
            'roc_auc': float(roc_auc_score(target, probability)),
            'pr_auc': float(average_precision_score(target, probability)),
            'brier_score': float(brier_score_loss(target, probability)),
            'threshold': float(threshold),
            'precision': float(precision_score(target, prediction, zero_division=0)),
            'recall': float(recall_score(target, prediction, zero_division=0)),
            'f1': float(f1_score(target, prediction, zero_division=0)),
            'confusion_matrix': {'tn': int(tn), 'fp': int(fp), 'fn': int(fn), 'tp': int(tp)}}


def choose_threshold(target, probability):
    candidates = np.linspace(0.05, 0.95, 181)
    scored = [(f1_score(target, probability >= value, zero_division=0), value)
              for value in candidates]
    return float(max(scored, key=lambda item: (item[0], -abs(item[1] - .5)))[1])


def yearly_metrics(frame, probability, threshold):
    output = {}
    for year in sorted(frame['race_date'].str[:4].unique()):
        mask = frame['race_date'].str.startswith(year).to_numpy()
        target = frame.loc[mask, TARGET].to_numpy()
        output[year] = (metrics(target, probability[mask], threshold)
                        if len(np.unique(target)) == 2 else
                        {'rows': int(mask.sum()), 'positives': int(target.sum()),
                         'note': 'Both outcomes required for ROC/PR metrics'})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--model-output', required=True, type=Path)
    parser.add_argument('--report-output', required=True, type=Path)
    parser.add_argument('--model-name', default='pooled-out-braking')
    args = parser.parse_args()
    input_bytes = args.input.read_bytes()
    input_sha256 = hashlib.sha256(input_bytes).hexdigest()
    frame = pd.read_parquet(io.BytesIO(input_bytes))
    validate_columns(frame.columns)
    # Lap-one candidates are retained for audit, but start-pack dynamics are
    # intentionally excluded until they have their own validated treatment.
    if 'model_eligible' in frame.columns:
        frame = frame[frame['model_eligible'].fillna(True)].copy()
    expected = {'train', 'validation', 'test'}
    if set(frame['dataset_split'].dropna()) != expected:
        raise ValueError(f'dataset_split must contain exactly {sorted(expected)}')
    subsets = {name: frame[frame['dataset_split'] == name].copy() for name in expected}
    for name, subset in subsets.items():
        if subset[TARGET].nunique() < 2:
            raise ValueError(f'{name} data must contain both outcomes')
    train, validation, test = subsets['train'], subsets['validation'], subsets['test']
    tuning = []
    for c_value in (.01, .03, .1, .3, 1., 3., 10.):
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
    validation_probability = model.predict_proba(validation[list(FEATURES)])[:, 1]
    threshold = choose_threshold(validation[TARGET].to_numpy(), validation_probability)
    test_probability = model.predict_proba(test[list(FEATURES)])[:, 1]
    report = {'model': 'class-balanced logistic regression', 'input_sha256': input_sha256,
              'model_scope': 'pooled', 'model_name': args.model_name,
              'features': {'numeric': list(MODEL_NUMERIC),
                           'categorical': list(MODEL_CATEGORICAL)},
              'selected_regularization_c': selected['c'], 'tuning': tuning,
              'validation': metrics(validation[TARGET].to_numpy(), validation_probability, threshold),
              'test': metrics(test[TARGET].to_numpy(), test_probability, threshold),
              'test_by_year': yearly_metrics(test, test_probability, threshold),
              'split_counts': {name: {'rows': int(len(subset)),
                                      'successes': int(subset[TARGET].sum())}
                               for name, subset in subsets.items()}}
    artifact = {'pipeline': model, 'threshold': threshold, 'input_sha256': input_sha256,
                'model_scope': 'pooled', 'model_name': args.model_name,
                'features': report['features'], 'report': report}
    args.model_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.model_output)
    args.report_output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'selected_c': selected['c'], 'threshold': threshold,
                      'validation': report['validation'], 'test': report['test']}, indent=2))


if __name__ == '__main__':
    main()
