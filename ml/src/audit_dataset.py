"""Audit downloaded OpenF1 data and conservative model-attempt extraction."""

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from prepare_data import build_session
from schema import NUMERIC_FEATURES, CATEGORICAL_FEATURES


EXPECTED_ENDPOINTS = {
    'drivers', 'position', 'overtakes', 'intervals', 'race_control', 'weather',
    'laps', 'stints', 'pit', 'car_data', 'location', 'derived',
}
FEATURES = (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path,
                        help='One driver/year folder containing session folders')
    parser.add_argument('--driver', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    sessions = sorted((path for path in args.input.iterdir()
                       if path.is_dir() and path.name.isdigit()), key=lambda path: int(path.name))
    report = {'input': str(args.input), 'driver_number': args.driver, 'sessions': []}
    all_rows = []
    for session in sessions:
        present = {path.name for path in session.iterdir() if path.is_dir()}
        missing = sorted(EXPECTED_ENDPOINTS - present)
        windows_path = session / 'derived' / 'candidate_windows.parquet'
        no_windows = windows_path.exists() and pq.read_table(windows_path).num_rows == 0
        if no_windows:
            missing = [name for name in missing if name not in {'car_data', 'location'}]
        entry = {'session_key': int(session.name), 'missing_endpoints': missing}
        try:
            rows, ambiguous = build_session(session, args.driver)
            successes = sum(row['overtake_success'] for row in rows)
            entry.update(attempts=len(rows), successes=successes,
                         failures=len(rows) - successes, ambiguous_excluded=ambiguous,
                         status='complete' if not missing else 'incomplete')
            all_rows.extend(rows)
        except Exception as exc:
            entry.update(attempts=0, successes=0, failures=0, ambiguous_excluded=0,
                         status='error', error=str(exc))
        report['sessions'].append(entry)

    missing_features = {feature: sum(row.get(feature) is None for row in all_rows)
                        for feature in FEATURES}
    successes = sum(row['overtake_success'] for row in all_rows)
    report['summary'] = {
        'sessions': len(sessions),
        'complete_sessions': sum(row['status'] == 'complete' for row in report['sessions']),
        'error_sessions': sum(row['status'] == 'error' for row in report['sessions']),
        'attempts': len(all_rows),
        'successes': successes,
        'failures': len(all_rows) - successes,
        'success_rate': successes / len(all_rows) if all_rows else None,
        'ambiguous_excluded': sum(row['ambiguous_excluded'] for row in report['sessions']),
        'missing_feature_values': missing_features,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')

    print('session  status      attempts  success  failure  ambiguous')
    for row in report['sessions']:
        print(f"{row['session_key']:<8} {row['status']:<11} {row['attempts']:<9} "
              f"{row['successes']:<8} {row['failures']:<8} {row['ambiguous_excluded']}")
    summary = report['summary']
    print(f"\nTotal: {summary['attempts']} attempts, {summary['successes']} successes, "
          f"{summary['failures']} failures, {summary['ambiguous_excluded']} ambiguous excluded")
    print(f'Report: {args.output}')


if __name__ == '__main__':
    main()
