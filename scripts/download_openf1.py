"""Resumable, single-attempt OpenF1 ingestion. See scripts/README.md."""
import argparse
from bisect import bisect_right
from http.client import IncompleteRead, RemoteDisconnected
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

BASE = 'https://api.openf1.org/v1/'
VERSION = 1
SHARED = ('position', 'overtakes', 'race_control', 'weather')
INTERVAL_CONTEXT_GAP = 1.0
MIN_ATTACK_SPEED_DELTA_KPH = 20


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def completed_races(sessions, now):
    return [s for s in sessions if s.get('session_name') == 'Race'
            and not s.get('is_cancelled') and s.get('date_end')
            and utc(s['date_end']) + timedelta(minutes=30) < now]


def save_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2))
    os.replace(temp, path)


def parquet_table(pa, rows):
    """Make API columns Parquet-safe without discarding sentinel strings."""
    if not rows:
        return pa.table({'_empty': pa.array([], type=pa.bool_())})
    normalized = [dict(row) for row in rows]
    keys = {key for row in rows for key in row}
    for key in keys:
        values = [row.get(key) for row in rows if row.get(key) is not None]
        kinds = {type(value) for value in values}
        numeric = kinds and all(kind in (int, float) for kind in kinds)
        if len(kinds) > 1 and not numeric:
            for row in normalized:
                value = row.get(key)
                if value is not None:
                    row[key] = value if isinstance(value, str) else json.dumps(value, separators=(',', ':'))
    return pa.Table.from_pylist(normalized)


def same_lap_overtakes(overtakes, laps):
    """Keep only passes where both drivers are on the same numbered lap."""
    by_driver = {}
    for lap in laps:
        if lap.get('date_start') and lap.get('lap_number') is not None:
            by_driver.setdefault(lap['driver_number'], []).append((utc(lap['date_start']).timestamp(), lap['lap_number']))
    for timeline in by_driver.values():
        timeline.sort()

    def lap_at(driver, date):
        timeline = by_driver.get(driver, [])
        index = bisect_right(timeline, (utc(date).timestamp(), float('inf'))) - 1
        return timeline[index][1] if index >= 0 else None

    filtered = []
    for overtake in overtakes:
        attacking_lap = lap_at(overtake['overtaking_driver_number'], overtake['date'])
        defending_lap = lap_at(overtake['overtaken_driver_number'], overtake['date'])
        if attacking_lap is not None and attacking_lap == defending_lap:
            filtered.append({**overtake, 'overtaking_lap_number': attacking_lap,
                             'overtaken_lap_number': defending_lap, 'same_lap': True})
    return filtered


def candidate_windows(intervals, positions, overtakes, selected_driver, driver_numbers,
                      laps=None, max_gap=0.5, padding_seconds=15):
    """Find close-running windows involving the selected driver and their adjacent rival."""
    timelines = {}
    for row in positions:
        if row.get('date') and row.get('position') is not None:
            timelines.setdefault(row['driver_number'], []).append(
                (utc(row['date']).timestamp(), row['position']))
    for timeline in timelines.values():
        timeline.sort()

    lap_timelines = {}
    for row in laps or []:
        if row.get('date_start') and row.get('lap_number') is not None:
            lap_timelines.setdefault(row['driver_number'], []).append(
                (utc(row['date_start']).timestamp(), row['lap_number']))
    for timeline in lap_timelines.values():
        timeline.sort()

    def position_at(driver, timestamp):
        timeline = timelines.get(driver, [])
        index = bisect_right(timeline, (timestamp, float('inf'))) - 1
        return timeline[index][1] if index >= 0 else None

    def lap_at(driver, timestamp):
        timeline = lap_timelines.get(driver, [])
        index = bisect_right(timeline, (timestamp, float('inf'))) - 1
        return timeline[index][1] if index >= 0 else None

    raw = []

    def add(date, drivers):
        center = utc(date)
        delta = timedelta(seconds=padding_seconds)
        raw.append((center - delta, center + delta, set(drivers)))

    for row in intervals:
        if not row.get('date') or row.get('driver_number') is None:
            continue
        try:
            gap = float(row.get('interval'))
        except (TypeError, ValueError):
            continue
        if gap < 0 or gap > max_gap:
            continue
        timestamp = utc(row['date']).timestamp()
        driver = row['driver_number']
        driver_position = position_at(driver, timestamp)
        selected_position = position_at(selected_driver, timestamp)
        if driver_position is None or selected_position is None:
            continue
        rival = None
        if driver == selected_driver and driver_position > 1:
            rival = next((number for number in driver_numbers
                          if position_at(number, timestamp) == driver_position - 1), None)
        elif driver_position == selected_position + 1:
            rival = driver
        if rival is not None:
            if not laps or lap_at(selected_driver, timestamp) == lap_at(rival, timestamp):
                add(row['date'], (selected_driver, rival))

    # Successful same-lap passes are always retained even if interval sampling missed 0.2 s.
    for row in overtakes:
        attacker = row['overtaking_driver_number']
        defender = row['overtaken_driver_number']
        if selected_driver in (attacker, defender):
            add(row['date'], (attacker, defender))

    merged = []
    for start, end, drivers in sorted(raw, key=lambda item: item[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]), merged[-1][2] | drivers)
        else:
            merged.append((start, end, drivers))
    return merged


def has_attack_telemetry(rows_by_driver, selected_driver, rivals, return_events=False):
    """Return whether a window contains the minimum car-data attack signature."""
    def timeline(number):
        return sorted((utc(row['date']).timestamp(), row) for row in rows_by_driver.get(number, [])
                      if row.get('date'))

    def brake_onsets(items):
        result = []
        for index in range(1, len(items) - 1):
            at, row = items[index]
            if (row.get('brake') and not items[index - 1][1].get('brake')
                    and items[index + 1][1].get('brake')):
                prior = [sample for when, sample in items if at - 1 <= when < at]
                if prior and not any(sample.get('brake') for sample in prior):
                    result.append((at, row))
        return result

    def nearest(items, at, tolerance=2):
        if not items:
            return None
        times = [item[0] for item in items]
        index = bisect_right(times, at)
        choices = items[max(0, index - 1):index + 1]
        best = min(choices, key=lambda item: abs(item[0] - at))
        return best if abs(best[0] - at) <= tolerance else None

    events = []
    attacker = timeline(selected_driver)
    for attacker_at, attacker_row in brake_onsets(attacker):
        attacker_speed = attacker_row.get('speed')
        if not isinstance(attacker_speed, (int, float)):
            continue
        for rival in rivals:
            defender = timeline(rival)
            defender_brakes = [item for item in brake_onsets(defender)
                               if 0 <= attacker_at - item[0] <= 5]
            defender_row = nearest(defender, attacker_at)
            defender_speed = defender_row[1].get('speed') if defender_row else None
            if (defender_brakes and isinstance(defender_speed, (int, float))
                    and attacker_speed - defender_speed >= MIN_ATTACK_SPEED_DELTA_KPH):
                if not return_events:
                    return True
                events.append(attacker_at)
    return sorted(set(events)) if return_events else False


def neutralized_at(moment, race_control):
    """Conservatively track yellow/red/safety-car periods until a clear/green message."""
    neutralized = False
    for row in sorted((row for row in race_control if row.get('date')),
                      key=lambda row: row['date']):
        if utc(row['date']) > moment:
            break
        text = ' '.join(str(row.get(key, '')) for key in ('category', 'flag', 'message')).upper()
        if 'GREEN' in text or 'CLEAR' in text:
            neutralized = False
        elif ('YELLOW' in text or 'RED FLAG' in text or 'SAFETY CAR' in text
              or 'VIRTUAL SAFETY CAR' in text):
            neutralized = True
    return neutralized


class Downloader:
    process_next_request_at = 0

    def __init__(self, root, spacing=3.0):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.pa, self.pq = pa, pq
        self.root, self.spacing = root, spacing
        root.mkdir(parents=True, exist_ok=True)
        self.state_path = root / 'manifest.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            'version': VERSION, 'next_request_at': 0, 'requests': {}}
        if self.state['version'] != VERSION:
            raise RuntimeError('Dataset version differs; use a new output directory.')

    def get(self, endpoint, params, refresh=False, empty_on_404=False):
        url = BASE + endpoint + '?' + urlencode(sorted(params.items()))
        key = hashlib.sha256(url.encode()).hexdigest()
        directory = self.root / str(params.get('session_key', 'catalog')) / endpoint
        directory.mkdir(parents=True, exist_ok=True)
        dest = directory / (key + '.parquet')
        previous = self.state['requests'].get(key)
        if not refresh and previous and previous['status'] == 'complete' and dest.exists():
            table = self.pq.read_table(dest)
            return [] if table.schema.names == ['_empty'] else table.to_pylist()
        self.state['requests'][key] = {
            'url': url, 'status': 'pending', 'rate_limit_retries': 0,
            'network_retries': 0}
        while True:
            delay = max(0, self.state['next_request_at'] - time.time(),
                        Downloader.process_next_request_at - time.time())
            if delay:
                time.sleep(delay)
            self.state['next_request_at'] = time.time() + self.spacing
            Downloader.process_next_request_at = self.state['next_request_at']
            save_json(self.state_path, self.state)
            print(f'GET {endpoint} {params}', flush=True)
            try:
                with urlopen(url, timeout=90) as response:
                    rows = json.load(response)
                if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                    raise ValueError('Unexpected API response; expected a list of records')
                table = parquet_table(self.pa, rows)
                temp = dest.with_suffix('.partial')
                self.pq.write_table(table, temp, compression='zstd')
                os.replace(temp, dest)
                self.state['requests'][key].update(
                    status='complete', rows=len(rows), file=str(dest),
                    fetched_at=datetime.now(timezone.utc).isoformat())
                save_json(self.state_path, self.state)
                return rows
            except Exception as exc:
                if empty_on_404 and isinstance(exc, HTTPError) and exc.code == 404:
                    table = parquet_table(self.pa, [])
                    temp = dest.with_suffix('.partial')
                    self.pq.write_table(table, temp, compression='zstd')
                    os.replace(temp, dest)
                    self.state['requests'][key].update(
                        status='complete', rows=0, file=str(dest),
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        note='API returned 404 for this telemetry window; stored as empty')
                    save_json(self.state_path, self.state)
                    return []
                if isinstance(exc, HTTPError) and exc.code == 429:
                    retry_after = exc.headers.get('Retry-After', '60')
                    try:
                        server_cooldown = float(retry_after)
                    except ValueError:
                        from email.utils import parsedate_to_datetime
                        try:
                            server_cooldown = parsedate_to_datetime(retry_after).timestamp() - time.time()
                        except (ValueError, TypeError):
                            server_cooldown = 60
                    retries = self.state['requests'][key]['rate_limit_retries'] + 1
                    cooldown = max(server_cooldown, min(900, 120 * (2 ** (retries - 1))))
                    resume_at = time.time() + cooldown
                    self.state['next_request_at'] = resume_at
                    Downloader.process_next_request_at = resume_at
                    self.state['requests'][key].update(
                        status='rate_limited', error=str(exc), rate_limit_retries=retries,
                        retry_at=datetime.fromtimestamp(resume_at, timezone.utc).isoformat())
                    save_json(self.state_path, self.state)
                    print(f'Rate limited. Retrying in {cooldown:.0f} seconds.', flush=True)
                    continue
                if (isinstance(exc, HTTPError) and exc.code in (408, 425, 500, 502, 503, 504)
                        or not isinstance(exc, HTTPError) and isinstance(exc, (
                            IncompleteRead, RemoteDisconnected, URLError,
                            TimeoutError, ConnectionError, json.JSONDecodeError))):
                    retries = self.state['requests'][key]['network_retries'] + 1
                    if retries <= 5:
                        cooldown = min(120, 15 * (2 ** (retries - 1)))
                        resume_at = time.time() + cooldown
                        self.state['next_request_at'] = resume_at
                        Downloader.process_next_request_at = resume_at
                        self.state['requests'][key].update(
                            status='connection_retry', error=str(exc),
                            network_retries=retries,
                            retry_at=datetime.fromtimestamp(resume_at, timezone.utc).isoformat())
                        save_json(self.state_path, self.state)
                        print(f'Connection interrupted. Retrying in {cooldown:.0f} seconds '
                              f'({retries}/5).', flush=True)
                        continue
                self.state['requests'][key].update(status='failed', error=str(exc))
                save_json(self.state_path, self.state)
                raise

    def write_derived(self, session_key, name, rows):
        directory = self.root / str(session_key) / 'derived'
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f'{name}.parquet'
        temp = destination.with_suffix('.partial')
        self.pq.write_table(parquet_table(self.pa, rows), temp, compression='zstd')
        os.replace(temp, destination)


def driver_slug(output, year, driver):
    """Resolve a number to a stable, human-readable folder component."""
    catalog = Downloader(output / '.catalog')
    sessions = catalog.get('sessions', {'year': year, 'session_name': 'Race'})
    races = completed_races(sessions, datetime.now(timezone.utc))
    for race in sorted(races, key=lambda row: row['date_start'], reverse=True):
        drivers = catalog.get('drivers', {'session_key': race['session_key']})
        match = next((row for row in drivers if row.get('driver_number') == driver), None)
        if match:
            name = match.get('full_name') or match.get('broadcast_name') or f'driver-{driver}'
            ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
            return re.sub(r'[^a-z0-9]+', '-', ascii_name.lower()).strip('-')
    raise ValueError(f'Driver {driver} was not found in a completed {year} race.')


def collect(client, year, driver, session_keys=None, all_opponents=False,
            max_gap=0.5, window_seconds=15):
    # Refresh only the catalog on rerun to discover newly completed races.
    sessions = client.get('sessions', {'year': year, 'session_name': 'Race'}, refresh=True)
    races = completed_races(sessions, datetime.now(timezone.utc))
    if session_keys:
        races = [s for s in races if s['session_key'] in session_keys]
    for race in sorted(races, key=lambda s: s['date_start']):
        session = race['session_key']
        drivers = client.get('drivers', {'session_key': session})
        numbers = sorted({row['driver_number'] for row in drivers})
        if driver not in numbers:
            continue
        client.get('meetings', {'meeting_key': race['meeting_key']})
        optional_shared = {'overtakes', 'race_control', 'weather'}
        shared = {endpoint: client.get(endpoint, {'session_key': session},
                                       empty_on_404=endpoint in optional_shared)
                  for endpoint in SHARED}
        # Keep one-second interval context for closing-rate calculation, but only
        # gaps within max_gap create telemetry candidate windows.
        intervals = client.get('intervals', {
            'session_key': session, 'interval<': max(INTERVAL_CONTEXT_GAP, max_gap)},
                               empty_on_404=True)
        relevant_overtakes = [row for row in shared['overtakes']
                              if driver in (row['overtaking_driver_number'], row['overtaken_driver_number'])]
        provisional = candidate_windows(intervals, shared['position'], relevant_overtakes,
                                        driver, numbers, max_gap=max_gap,
                                        padding_seconds=window_seconds)
        involved = {driver}
        for _, _, window_drivers in provisional:
            involved.update(window_drivers)

        # Driver-specific context is much smaller than downloading these endpoints race-wide.
        laps, stints, pits = [], [], []
        for number in sorted(involved):
            query = {'session_key': session, 'driver_number': number}
            laps.extend(client.get('laps', query, empty_on_404=True))
            stints.extend(client.get('stints', query, empty_on_404=True))
            pits.extend(client.get('pit', query, empty_on_404=True))
        overtakes = same_lap_overtakes(relevant_overtakes, laps)
        client.write_derived(session, 'same_lap_overtakes', overtakes)
        windows = candidate_windows(intervals, shared['position'], overtakes,
                                    driver, numbers, laps, max_gap, window_seconds)

        # Pit-lane proximity is not an on-track overtaking opportunity.
        pit_times = [utc(row['date']) for row in pits if row.get('date')]
        windows = [(start, end, window_drivers) for start, end, window_drivers in windows
                   if not any(start <= pit_time <= end for pit_time in pit_times)
                   and not neutralized_at(start + (end - start) / 2, shared['race_control'])]
        qualified_windows = []
        for start, end, window_drivers in windows:
            targets = sorted(window_drivers) if all_opponents else [driver]
            car_by_driver = {}
            for number in targets:
                # Car data is the inexpensive first stage used to reject windows
                # with no credible braking attack before requesting location.
                car_by_driver[number] = client.get(
                    'car_data', {'session_key': session, 'driver_number': number,
                                 'date>': start.isoformat(), 'date<': end.isoformat()},
                    empty_on_404=True)
            confirmed = any(start <= utc(row['date']) <= end for row in overtakes
                            if driver in (row['overtaking_driver_number'],
                                          row['overtaken_driver_number']))
            rivals = set(window_drivers) - {driver}
            qualified = (confirmed or not all_opponents
                         or has_attack_telemetry(car_by_driver, driver, rivals))
            if not qualified:
                continue
            qualified_windows.append((start, end, window_drivers))
            for number in targets:
                # urlencode supplies '=': date> becomes date>= in query syntax.
                client.get('location', {'session_key': session, 'driver_number': number,
                                        'date>': start.isoformat(), 'date<': end.isoformat()},
                           empty_on_404=True)
        client.write_derived(session, 'candidate_windows', [
            {'session_key': session, 'date_start': start.isoformat(),
             'date_end': end.isoformat(), 'driver_numbers': sorted(window_drivers)}
            for start, end, window_drivers in qualified_windows
        ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', required=True, type=int)
    parser.add_argument('--driver', required=True, type=int, help='Season-specific driver number')
    parser.add_argument('--session', action='append', type=int, help='Optional race session key; repeatable')
    parser.add_argument('--all-opponents', action='store_true', help='Also download every opponent’s car/location data (larger)')
    parser.add_argument('--output', type=Path, default=Path('data/openf1'), help='Base data directory')
    parser.add_argument('--max-gap', type=float, default=0.5,
                        help='Maximum interval in seconds for a candidate opportunity (default: 0.5)')
    parser.add_argument('--window-seconds', type=int, default=15,
                        help='Telemetry padding before and after a candidate moment (default: 15)')
    args = parser.parse_args()
    if (args.year < 2023 or args.year > datetime.now(timezone.utc).year or args.driver < 1
            or args.max_gap <= 0 or not 1 <= args.window_seconds <= 120):
        parser.error('Use a valid year/driver, a positive gap, and a window of 1–120 seconds.')
    slug = driver_slug(args.output, args.year, args.driver)
    driver_root = args.output / slug
    dataset_root = driver_root / str(args.year)
    legacy_root = args.output / f'{slug}-{args.year}'
    if legacy_root.exists() and not dataset_root.exists():
        driver_root.mkdir(parents=True, exist_ok=True)
        legacy_root.rename(dataset_root)
        print(f'Migrated existing dataset to {dataset_root}', flush=True)
    elif legacy_root.exists() and dataset_root.exists():
        parser.error(f'Both legacy and current dataset folders exist: {legacy_root} and '
                     f'{dataset_root}. Resolve them before continuing.')
    dataset_root.mkdir(parents=True, exist_ok=True)
    # Kernel lock is released even on interruption; prevents concurrent writers.
    import fcntl
    with (dataset_root / '.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, 'Another downloader is using this output directory.\n')
        try:
            collect(Downloader(dataset_root), args.year, args.driver, args.session,
                    args.all_opponents, args.max_gap, args.window_seconds)
        except KeyboardInterrupt:
            parser.exit(130, '\nPaused. Rerun the same command to resume.\n')
        except Exception as exc:
            parser.exit(1, f'Stopped: {exc}\nNo automatic retry. Rerun the same command to resume.\n')
    print('Complete. Rerun later to discover new races.')


if __name__ == '__main__':
    main()
