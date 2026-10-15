"""Export compact, static Overtakes-tab data from completed local sessions.

The browser receives only the fields rendered by the UI. Raw telemetry and
Parquet inputs remain local and are never copied into the publishable output.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from prepare_data import read_rows, stamp
from prepare_pooled import accepted_session_rows, complete_files


PRE_OVERTAKE_WINDOW_SECONDS = 8
POST_OVERTAKE_WINDOW_SECONDS = 2
FORMAT_VERSION = 1


def event_rows(session_dir, metadata, year):
    """Export only accepted successful pooled attempts, never raw pass records."""
    accepted, _ = accepted_session_rows(session_dir, metadata, year)
    successes = [row for row in accepted if row['overtake_success']]
    if not successes:
        return []
    telemetry = defaultdict(list)
    for row in read_rows(session_dir / 'car_data'):
        if row.get('date') and row.get('driver_number') is not None:
            telemetry[row['driver_number']].append(row)
    telemetry_times = {}
    for number, rows in telemetry.items():
        rows.sort(key=lambda row: stamp(row['date']))
        telemetry_times[number] = [stamp(row['date']) for row in rows]

    events = []
    for attempt in successes:
        passer = attempt['attacker_driver_number']
        defender = attempt['defender_driver_number']
        event_at = stamp(attempt['brake_onset_at'])
        passing_window = samples_in_window(
            telemetry.get(passer, []), telemetry_times.get(passer, []), event_at,
        )
        defending_window = samples_in_window(
            telemetry.get(defender, []), telemetry_times.get(defender, []), event_at,
        )
        passer_brake = nearest_sample(passing_window, attempt['brake_onset_at'])
        defender_brake = nearest_sample(defending_window, event_at - attempt['brake_onset_delta_seconds'])
        if passer_brake is None or defender_brake is None:
            continue
        defender_at_passer_brake = nearest_sample(defending_window, passer_brake['date'])
        if defender_at_passer_brake is None:
            continue
        events.append({
            'event_id': attempt['event_id'], 'date': attempt['brake_onset_at'],
            'overtaking_driver_number': passer,
            'overtaken_driver_number': defender,
            'lap_number': attempt['lap_number'],
            'brake_onset_advantage_ms': round(attempt['brake_onset_delta_seconds'] * 1000),
            'passer': inputs(passer_brake),
            'defender_at_passer_brake': inputs(defender_at_passer_brake),
            'passer_brake_offset_ms': round((stamp(passer_brake['date']) - event_at) * 1000),
            'defender_brake_offset_ms': round((stamp(defender_brake['date']) - event_at) * 1000),
            'passer_trace': trace(passing_window, event_at),
            'defender_trace': trace(defending_window, event_at),
        })
    return sorted(events, key=lambda row: row['date'])


def samples_in_window(rows, times, event_at):
    start = event_at - PRE_OVERTAKE_WINDOW_SECONDS
    end = event_at + POST_OVERTAKE_WINDOW_SECONDS
    return rows[bisect_left(times, start):bisect_right(times, end)]


def nearest_sample(rows, target_date):
    if not rows:
        return None
    target = target_date if isinstance(target_date, (int, float)) else stamp(target_date)
    return min(rows, key=lambda row: abs(stamp(row['date']) - target))


def inputs(row):
    return {key: row.get(key, 0) for key in ('speed', 'brake', 'throttle')}


def trace(rows, event_at):
    """Keep the compact speed/brake trace needed by the browser chart."""
    return [
        {'t': round((stamp(row['date']) - event_at) * 1000), 'speed': row.get('speed', 0),
         'brake': row.get('brake', 0)}
        for row in rows
    ]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(',', ':')) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('data/openf1-pooled'))
    parser.add_argument('--output', type=Path, default=Path('public/overtakes'))
    args = parser.parse_args()

    if args.output.exists():
        shutil.rmtree(args.output)
    sessions = []
    for year_dir in sorted(args.input.glob('[0-9][0-9][0-9][0-9]')):
        catalog = {row['session_key']: row for row in read_rows(year_dir / 'catalog/sessions')}
        meetings = {row['meeting_key']: row for row in read_rows(year_dir / 'catalog/meetings')}
        for session_dir in sorted(year_dir.iterdir()):
            if not session_dir.name.isdigit() or not (session_dir / 'derived/pooled_complete.json').exists():
                continue
            session_key = int(session_dir.name)
            session = catalog.get(session_key)
            meeting = meetings.get(session.get('meeting_key')) if session else None
            if not session or not meeting or session.get('session_name') not in ('Race', 'Sprint'):
                continue
            complete_files(session_dir)
            events = event_rows(session_dir, session, int(year_dir.name))
            available_drivers = {
                number for event in events
                for number in (event['overtaking_driver_number'], event['overtaken_driver_number'])
            }
            drivers = [{
                'driver_number': row['driver_number'], 'full_name': row['full_name'],
                'name_acronym': row.get('name_acronym'), 'team_name': row.get('team_name'),
                'team_colour': row.get('team_colour'),
            } for row in read_rows(session_dir / 'drivers') if row['driver_number'] in available_drivers]
            drivers.sort(key=lambda row: row['full_name'])
            write_json(args.output / 'sessions' / f'{session_key}.json', {'events': events})
            sessions.append({
                'year': int(year_dir.name), 'meeting_key': session['meeting_key'],
                'meeting_name': meeting['meeting_name'], 'date_start': meeting['date_start'],
                'session_key': session_key, 'session_name': session['session_name'], 'drivers': drivers,
            })
            print(f'{session_key}: {len(events)} qualifying events')
    sessions.sort(key=lambda row: (row['year'], row['date_start']))
    write_json(args.output / 'manifest.json', {
        'format_version': FORMAT_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sessions': sessions,
    })
    print(f'Exported {len(sessions)} races to {args.output}')


if __name__ == '__main__':
    main()
