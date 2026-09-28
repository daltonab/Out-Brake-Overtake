"""Export a trained sklearn artifact as browser-readable logistic-model JSON."""
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
import joblib


def scalar(value):
    return value.item() if hasattr(value, 'item') else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--model-name', default='pooled-out-braking',
                        help='Stable label for this exported model.')
    parser.add_argument('--driver',
                        help='Optional legacy driver-specific label. Omit for pooled models.')
    args = parser.parse_args()
    artifact = joblib.load(args.model)
    pipeline = artifact['pipeline']; transform = pipeline.named_steps['transform']
    classifier = pipeline.named_steps['model']
    numeric = transform.named_transformers_['numeric']
    categorical = transform.named_transformers_['categorical']
    numeric_imputer = numeric.named_steps['impute']; scaler = numeric.named_steps['scale']
    categorical_imputer = categorical.named_steps['impute']
    encoder = categorical.named_steps['encode']
    # New artifacts declare their pooled scope. Driver inference preserves
    # compatibility for the historical Max baseline artifact.
    scope = artifact.get('model_scope') or ('driver_specific' if args.driver else 'pooled')
    model_name = artifact.get('model_name') or args.model_name
    export = {
        'format_version': 1, 'model_type': 'logistic_regression',
        'model_scope': scope, 'model_name': model_name,
        # Retained for the existing UI and old driver-specific exports. Pooled
        # exports deliberately contain null rather than a misleading driver.
        'driver': args.driver,
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'decision_threshold': artifact['threshold'],
        'numeric': {'features': artifact['features']['numeric'],
                    'impute_medians': [scalar(v) for v in numeric_imputer.statistics_],
                    'means': [scalar(v) for v in scaler.mean_],
                    'scales': [scalar(v) for v in scaler.scale_]},
        'categorical': {'features': artifact['features']['categorical'],
                        'impute_values': [scalar(v) for v in categorical_imputer.statistics_],
                        'categories': [[scalar(v) for v in values] for values in encoder.categories_]},
        'encoded_feature_order': [str(v) for v in transform.get_feature_names_out()],
        'coefficients': [scalar(v) for v in classifier.coef_[0]],
        'intercept': scalar(classifier.intercept_[0]), 'evaluation': artifact['report']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(export, indent=2) + '\n')
    print(f'Exported browser model to {args.output}')


if __name__ == '__main__':
    main()
