"""Download model-ready OpenF1 source data once per race for a pooled model."""

import argparse
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.client import IncompleteRead, RemoteDisconnected
import json
from pathlib import Path
import time
import fcntl
from urllib.error import HTTPError, URLError

from download_openf1 import (Downloader, has_attack_telemetry,
                             neutralized_at, same_lap_overtakes, utc)
from download_openf1 import save_json


FIRST_OPENF1_YEAR = 2023
PIPELINE_VERSION = 2
INTERVAL_CONTEXT_GAP = 1.0
DEFAULT_CANDIDATE_GAP = 0.5
DEFAULT_WINDOW_SECONDS = 15


def completed_racing_sessions(sessions, now):
    """Include main races and sprints, never Sprint Qualifying/Shootout."""
    return [row for row in sessions if row.get('session_name') in ('Race', 'Sprint')
            and not row.get('is_cancelled') and row.get('date_end')
            and utc(row['date_end']) + timedelta(minutes=30) < now]


def value_at(timeline, at):
    index = bisect_right(timeline, (at, float('inf'))) - 1
    return timeline[index][1] if index >= 0 else None


def merge_ranges(ranges):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def pair_windows(intervals, positions, overtakes, laps, candidate_gap, padding_seconds,
                 pits=(), race_control=()):
    """Build and merge close-running windows for every attacker/defender pair."""
    positions_by_driver = defaultdict(list)
    for row in positions:
        if row.get('date') and row.get('position') is not None:
            positions_by_driver[row['driver_number']].append(
                (utc(row['date']).timestamp(), row['position']))
    for timeline in positions_by_driver.values():
        timeline.sort()

    laps_by_driver = defaultdict(list)
    for row in laps:
        if row.get('date_start') and row.get('lap_number') is not None:
            laps_by_driver[row['driver_number']].append(
                (utc(row['date_start']).timestamp(), row['lap_number']))
    for timeline in laps_by_driver.values():
        timeline.sort()

    def lap_at(driver, at):
        return value_at(laps_by_driver.get(driver, []), at)

    raw = []
    padding = timedelta(seconds=padding_seconds)
    driver_numbers = tuple(positions_by_driver)
    for row in intervals:
        if not row.get('date') or row.get('driver_number') is None:
            continue
        try:
            gap = float(row.get('interval'))
        except (TypeError, ValueError):
            continue
        if not 0 < gap <= candidate_gap:
            continue
        at = utc(row['date'])
        timestamp = at.timestamp()
        attacker = row['driver_number']
        attacker_position = value_at(positions_by_driver.get(attacker, []), timestamp)
        if attacker_position is None or attacker_position <= 1:
            continue
        defender = next((number for number in driver_numbers
                         if value_at(positions_by_driver[number], timestamp)
                         == attacker_position - 1), None)
        attacker_lap, defender_lap = lap_at(attacker, timestamp), lap_at(defender, timestamp)
        if (defender is not None and attacker_lap is not None and attacker_lap > 1
                and attacker_lap == defender_lap):
            raw.append({'start': at - padding, 'end': at + padding,
                        'attacker': attacker, 'defender': defender, 'confirmed': False})

    for row in overtakes:
        at = utc(row['date'])
        raw.append({'start': at - padding, 'end': at + padding,
                    'attacker': row['overtaking_driver_number'],
                    'defender': row['overtaken_driver_number'], 'confirmed': True})

    # Filter individual candidate moments before merging: a pit stop at the end
    # of a long following episode must not discard the entire episode.
    raw = [row for row in raw if eligible_moment(
        row['start'] + padding, row['attacker'], row['defender'], pits, race_control)]
    merged = []
    for row in sorted(raw, key=lambda item: (item['attacker'], item['defender'], item['start'])):
        if (merged and row['attacker'] == merged[-1]['attacker']
                and row['defender'] == merged[-1]['defender']
                and row['start'] <= merged[-1]['end']):
            merged[-1]['end'] = max(merged[-1]['end'], row['end'])
            merged[-1]['confirmed'] |= row['confirmed']
        else:
            merged.append(dict(row))
    return merged


def eligible_moment(at, attacker, defender, pits, race_control):
    return (not neutralized_at(at, race_control)
            and not any(row.get('date') and row.get('driver_number') in (attacker, defender)
                        and -15 <= (at - utc(row['date'])).total_seconds()
                        <= max(15, row.get('pit_duration') or row.get('lane_duration') or 0) + 15
                        for row in pits))


class MissingSourceData(Exception):
    """Required race data is temporarily absent; never checkpoint as complete."""


def verified_completion(client, completion, expected):
    try:
        recorded = json.loads(completion.read_text())
        if not all(recorded.get(key) == value for key, value in expected.items()):
            return False
        files = recorded.get('files', [])
        return bool(files) and all(
            (client.root / item['path']).is_file()
            and (client.root / item['path']).stat().st_size == item['size']
            and client.pq.read_metadata(client.root / item['path']).num_rows == item['rows']
            for item in files)
    except (OSError, ValueError, KeyError):
        return False


def grouped_driver_windows(windows):
    grouped = defaultdict(list)
    for row in windows:
        for number in (row['attacker'], row['defender']):
            grouped[number].append((row['start'], row['end']))
    return {number: merge_ranges(ranges) for number, ranges in grouped.items()}


def rows_between(rows, start, end):
    return [row for row in rows if row.get('date') and start <= utc(row['date']) <= end]


def closing_candidate(intervals, driver, timestamp, max_gap):
    samples = sorted((utc(row['date']).timestamp(), row['interval']) for row in intervals
                     if row.get('driver_number') == driver and row.get('date')
                     and isinstance(row.get('interval'), (int, float)))
    if not samples:
        return False
    index = min(range(len(samples)), key=lambda i: abs(samples[i][0] - timestamp))
    at, gap = samples[index]
    if index == 0 or abs(at - timestamp) > 4 or not 0 < gap <= max_gap:
        return False
    previous_at, previous_gap = samples[index - 1]
    # Keep all positive closing rates. The stronger 0.02 OR later physical
    # braking test cannot be completed until location data has been downloaded.
    return 0 < at - previous_at <= 10 and previous_gap > gap


def fetch_windowed(client, endpoint, session, windows_by_driver):
    rows = defaultdict(list)
    for number, ranges in sorted(windows_by_driver.items()):
        for start, end in ranges:
            result = client.get(endpoint, {
                'session_key': session, 'driver_number': number,
                'date>': start.isoformat(), 'date<': end.isoformat()}, empty_on_404=True)
            rows[number].extend(result)
    return rows


def required_source(client, session, endpoint):
    """Event/filter endpoints may legitimately return an empty HTTP 200 list."""
    params = {'session_key': session}
    if endpoint == 'intervals':
        params['interval<'] = INTERVAL_CONTEXT_GAP
    allow_empty = endpoint in {'overtakes', 'intervals', 'race_control'}
    try:
        rows = client.get(endpoint, params)
        if not rows and not allow_empty:
            rows = client.get(endpoint, params, refresh=True)
    except HTTPError as exc:
        if exc.code == 404:
            raise MissingSourceData(f'{endpoint} unavailable for race {session}') from exc
        raise
    if not rows and not allow_empty:
        raise MissingSourceData(f'{endpoint} missing for race {session}')
    return rows


def collect_race(client, race, candidate_gap, window_seconds):
    session = race['session_key']
    session_dir = client.root / str(session)
    completion = session_dir / 'derived' / 'pooled_complete.json'
    expected_config = {'version': PIPELINE_VERSION, 'candidate_gap': candidate_gap,
                       'window_seconds': window_seconds}
    if verified_completion(client, completion, expected_config):
        print(f'SKIP completed race {session}', flush=True)
        return

    def required(endpoint):
        return required_source(client, session, endpoint)

    drivers = required('drivers')
    client.get('meetings', {'meeting_key': race['meeting_key']})
    optional = {'weather', 'pit'}
    endpoints = ('position', 'overtakes', 'race_control', 'weather', 'laps', 'stints', 'pit')
    shared = {endpoint: (client.get(endpoint, {'session_key': session}, empty_on_404=True)
                         if endpoint in optional else required(endpoint))
              for endpoint in endpoints}
    intervals = required('intervals')
    overtakes = [row for row in same_lap_overtakes(shared['overtakes'], shared['laps'])
                 if (row.get('overtaking_lap_number') or 0) > 1]
    client.write_derived(session, 'same_lap_overtakes', overtakes)
    windows = pair_windows(intervals, shared['position'], overtakes, shared['laps'],
                           candidate_gap, window_seconds, shared['pit'], shared['race_control'])

    car = fetch_windowed(client, 'car_data', session, grouped_driver_windows(windows))
    qualified = []
    for row in windows:
        pair_car = {number: rows_between(car[number], row['start'], row['end'])
                    for number in (row['attacker'], row['defender'])}
        events = has_attack_telemetry(
            pair_car, row['attacker'], {row['defender']}, return_events=True)
        events = [at for at in events if closing_candidate(
            intervals, row['attacker'], at, candidate_gap)]
        # Protect positive candidates independently of the negative-only speed gate.
        events += [utc(event['date']).timestamp() for event in overtakes
                   if event['overtaking_driver_number'] == row['attacker']
                   and event['overtaken_driver_number'] == row['defender']
                   and row['start'] <= utc(event['date']) <= row['end']]
        for timestamp in sorted(set(events)):
            at = datetime.fromtimestamp(timestamp, timezone.utc)
            if eligible_moment(at, row['attacker'], row['defender'],
                               shared['pit'], shared['race_control']):
                qualified.append({**row, 'start': max(row['start'], at - timedelta(seconds=15)),
                                  'end': min(row['end'], at + timedelta(seconds=15))})

    fetch_windowed(client, 'location', session, grouped_driver_windows(qualified))
    client.write_derived(session, 'candidate_windows', [{
        'session_key': session, 'date_start': row['start'].isoformat(),
        'date_end': row['end'].isoformat(), 'attacker_driver_number': row['attacker'],
        'defender_driver_number': row['defender'],
        'confirmed_overtake': row['confirmed']} for row in qualified])
    completion.parent.mkdir(parents=True, exist_ok=True)
    files = [{'path': str(path.relative_to(client.root)), 'size': path.stat().st_size,
              'rows': client.pq.read_metadata(path).num_rows}
             for path in sorted(session_dir.rglob('*.parquet'))]
    save_json(completion, {
        **expected_config, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'drivers': len(drivers), 'candidate_windows': len(windows),
        'qualified_windows': len(qualified), 'files': files})
    print(f'COMPLETE race {session}: {len(qualified)}/{len(windows)} windows retained', flush=True)


def retryable(exc):
    if isinstance(exc, HTTPError):
        return exc.code in (408, 425, 429, 500, 502, 503, 504)
    return isinstance(exc, (IncompleteRead, RemoteDisconnected, URLError,
                            TimeoutError, ConnectionError, json.JSONDecodeError, MissingSourceData))


def run_with_transient_retry(description, operation):
    while True:
        try:
            return operation()
        except KeyboardInterrupt:
            raise SystemExit('\nPaused. Rerun the same command to resume.\n')
        except Exception as exc:
            if not retryable(exc):
                raise
            print(f'Temporary failure during {description}: {exc}. Retrying in 5 minutes.',
                  flush=True)
            time.sleep(300)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-year', type=int, default=FIRST_OPENF1_YEAR)
    parser.add_argument('--end-year', type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument('--output', type=Path, default=Path('data/openf1-pooled'))
    parser.add_argument('--candidate-gap', type=float, default=DEFAULT_CANDIDATE_GAP)
    parser.add_argument('--window-seconds', type=int, default=DEFAULT_WINDOW_SECONDS)
    args = parser.parse_args()
    current_year = datetime.now(timezone.utc).year
    if (args.start_year < FIRST_OPENF1_YEAR or args.end_year > current_year
            or args.start_year > args.end_year or not 0 < args.candidate_gap <= 1
            or not 15 <= args.window_seconds <= 120):
        parser.error(f'Use years {FIRST_OPENF1_YEAR}-{current_year}, a positive gap, '
                     'and a window from 15-120 seconds; gap must be at most 1 second.')

    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / '.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Another pooled downloader is using this output directory.')

    for year in range(args.start_year, args.end_year + 1):
        client = Downloader(args.output / str(year))
        sessions = run_with_transient_retry(
            f'{year} race discovery',
            lambda: client.get('sessions', {'year': year}, refresh=True))
        races = sorted(completed_racing_sessions(sessions, datetime.now(timezone.utc)),
                       key=lambda row: row['date_start'])
        for race in races:
            run_with_transient_retry(
                f'race {race["session_key"]}',
                lambda race=race: collect_race(
                    client, race, args.candidate_gap, args.window_seconds))
    print(f'All currently completed races and sprints from {args.start_year}-{args.end_year} are complete.')


if __name__ == '__main__':
    main()
