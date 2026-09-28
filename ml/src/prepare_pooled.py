"""Build pooled attempts from completed race/Sprint downloads; see POOLED_PREPROCESSING.md."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import unicodedata

import pyarrow as pa
import pyarrow.parquet as pq

from prepare_data import build_session, prepare_session, read_rows, stamp, timeline, value_at
from schema import REQUIRED_COLUMNS, NUMERIC_FEATURES


def driver_identity(row):
    name = row.get('full_name')
    if not name:
        raise ValueError(f'Missing full name for driver {row.get("driver_number")}')
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', normalized.casefold()).strip('-')


def neutralized(at, messages):
    """Replay ordered flags, keeping suspension, SC/VSC and sectors separate.

    TRACK CLEAR releases SC/VSC and local yellows, but a red-flag suspension
    remains until SESSION STARTED. Pit-exit lights do not describe track state.
    """
    suspended, safety_car, yellow_sectors = False, False, set()
    for when, row in messages:
        if when > at:
            break
        flag = str(row.get('flag') or '').upper()
        text = str(row.get('message') or '').upper()
        category = str(row.get('category') or '').upper()
        scope = str(row.get('scope') or '').upper()
        sector = row.get('sector')
        if category == 'SESSIONSTATUS':
            if text == 'SESSION STARTED':
                suspended = False
            elif text in ('SESSION ABORTED', 'SESSION STOPPED', 'SESSION FINISHED',
                          'SESSION ENDED'):
                suspended = True
        if 'PIT EXIT' in text or 'PIT ENTRY' in text:
            continue
        if 'SAFETY CAR' in text and 'DEPLOYED' in text:
            safety_car = True
        if 'ROLLING START PROCEDURE' in text and 'WILL RESUME' not in text:
            safety_car = True
        if flag == 'RED' or text == 'RED FLAG':
            suspended = True
        if flag in ('YELLOW', 'DOUBLE YELLOW'):
            yellow_sectors.add(sector)
        if flag in ('CLEAR', 'GREEN'):
            if scope == 'TRACK' or text == 'TRACK CLEAR':
                safety_car = False
                yellow_sectors.clear()
            elif scope == 'SECTOR' or sector is not None:
                yellow_sectors.discard(sector)
        # ENDING and IN THIS LAP are announcements, not a release to racing.
    return suspended or safety_car or bool(yellow_sectors)


def exclusion(row, windows, laps_by_driver, pits, messages):
    at = stamp(row['brake_onset_at'])
    attacker, defender = row['attacker_driver_number'], row['defender_driver_number']
    if not any(w.get('attacker_driver_number') == attacker
               and w.get('defender_driver_number') == defender
               and stamp(w['date_start']) <= at <= stamp(w['date_end']) for w in windows):
        return 'outside_qualified_window'
    if neutralized(at, messages):
        return 'neutralized'
    lap_numbers = []
    for number in (attacker, defender):
        laps = laps_by_driver.get(number, [])
        current = value_at(laps, at)
        if not current:
            return 'missing_lap_context'
        lap = current.get('lap_number')
        lap_numbers.append(lap)
        # Whole in/out laps are conservatively excluded when exact pit timing
        # is absent. Use each driver's own lap counter, never the attacker's for both.
        next_lap = next((r for _, r in laps if r.get('lap_number') == lap + 1), {})
        if current.get('is_pit_out_lap') or next_lap.get('is_pit_out_lap'):
            return 'pit_in_or_out_lap'
        for pit in pits:
            if pit.get('driver_number') != number or not pit.get('date'):
                continue
            duration = pit.get('lane_duration') or pit.get('pit_duration') or 0
            if stamp(pit['date']) - 15 <= at <= stamp(pit['date']) + duration + 15:
                return 'pit_proximity'
    if None in lap_numbers or lap_numbers[0] != lap_numbers[1]:
        return 'different_or_unknown_lap'
    return None


def assign_splits(rows, seed=42):
    """Shuffle whole weekends within each year, preserving all drivers/sessions."""
    years = defaultdict(set)
    for row in rows:
        years[row['year']].add(row['meeting_key'])
    mapping = {}
    for year, meetings in sorted(years.items()):
        meetings = sorted(meetings)
        random.Random(seed + year).shuffle(meetings)
        n = len(meetings)
        validation = max(1, round(n * .15)) if n >= 3 else 0
        test = max(1, round(n * .15)) if n >= 2 else 0
        train = n - validation - test
        for i, meeting in enumerate(meetings):
            mapping[year, meeting] = ('train' if i < train else
                                     'validation' if i < train + validation else 'test')
    for row in rows:
        row['dataset_split'] = mapping[row['year'], row['meeting_key']]


def complete_files(session_dir):
    marker = json.loads((session_dir / 'derived/pooled_complete.json').read_text())
    if not marker.get('files'):
        raise ValueError(f'{session_dir}: completion marker has no inventory')
    for item in marker['files']:
        path = session_dir.parent / item['path']
        if (not path.exists() or path.stat().st_size != item['size']
                or pq.read_metadata(path).num_rows != item['rows']):
            raise ValueError(f'Invalid completed file: {path}')


def summarize(rows):
    return {'rows': len(rows), 'successes': sum(r['overtake_success'] for r in rows),
            'failures': sum(not r['overtake_success'] for r in rows),
            'quality_flags': dict(Counter(f for r in rows for f in r['quality_flags'])),
            'missing_features': {f: sum(r.get(f) is None for r in rows)
                                 for f in NUMERIC_FEATURES}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('data/openf1-pooled'))
    parser.add_argument('--output', type=Path, default=Path('data/processed/pooled/attempts.parquet'))
    parser.add_argument('--report', type=Path, default=Path('ml/reports/pooled-preprocessing.json'))
    parser.add_argument('--session', type=int, action='append', help='Optional repeatable session key')
    parser.add_argument('--split-seed', type=int, default=42)
    args = parser.parse_args()
    rows, sessions, skipped = [], [], []
    for year_dir in sorted(args.input.glob('[0-9][0-9][0-9][0-9]')):
        catalog = {r['session_key']: r for r in read_rows(year_dir / 'catalog/sessions')}
        for session_dir in sorted(year_dir.iterdir()):
            if not session_dir.is_dir() or not session_dir.name.isdigit():
                continue
            key = int(session_dir.name)
            if args.session and key not in args.session:
                continue
            if not (session_dir / 'derived/pooled_complete.json').exists():
                skipped.append(key)
                continue
            complete_files(session_dir)
            metadata = catalog.get(key)
            if not metadata or metadata.get('session_name') not in ('Race', 'Sprint'):
                raise ValueError(f'Missing or unsupported session catalog entry: {key}')
            cache = {}
            def reader(path):
                if path not in cache:
                    cache[path] = read_rows(path)
                return cache[path]
            roster = {r['driver_number']: r for r in reader(session_dir / 'drivers')}
            identities = {n: driver_identity(r) for n, r in roster.items()}
            if len(set(identities.values())) != len(identities):
                raise ValueError(f'Duplicate driver identity in session {key}')
            windows = pq.read_table(session_dir / 'derived/candidate_windows.parquet').to_pylist()
            laps = reader(session_dir / 'laps')
            lap_timelines = {n: timeline(laps, n, 'date_start') for n in roster}
            pits = reader(session_dir / 'pit')
            messages = timeline(reader(session_dir / 'race_control'))
            reasons, session_rows, ambiguous = Counter(), [], 0
            context = prepare_session(session_dir, reader=reader)
            for number in sorted(roster):
                candidates, count = build_session(session_dir, number, context=context)
                ambiguous += count
                for row in candidates:
                    reason = exclusion(row, windows, lap_timelines, pits, messages)
                    if reason:
                        reasons[reason] += 1
                        continue
                    for role in ('attacker', 'defender'):
                        n = row[f'{role}_driver_number']
                        row[f'{role}_driver_id'] = identities[n]
                        row[f'{role}_driver_name'] = roster[n]['full_name']
                    row.update(year=int(year_dir.name), session_name=metadata['session_name'],
                               meeting_key=metadata['meeting_key'])
                    if not pits:
                        row['quality_flags'].append('pit_lap_fallback')
                    session_rows.append(row)
            rows.extend(session_rows)
            entry = {'session_key': key, 'year': int(year_dir.name),
                     'session_name': metadata['session_name'], **summarize(session_rows),
                     'excluded': dict(reasons), 'ambiguous': ambiguous}
            sessions.append(entry)
            print(json.dumps(entry), flush=True)
    if not sessions:
        raise ValueError('No completed matching sessions found; no output written')
    rows = list({r['event_id']: r for r in rows}.values())
    assign_splits(rows, args.split_seed)
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'split_seed': args.split_seed,
              'sessions': sessions, 'skipped_incomplete_sessions': skipped,
              'total': summarize(rows)}
    for label, field in [('by_driver', 'attacker_driver_id'), ('by_year', 'year'),
                         ('by_session_type', 'session_name'), ('by_split', 'dataset_split')]:
        report[label] = {str(value): summarize([r for r in rows if r[field] == value])
                         for value in sorted({r[field] for r in rows})}
    report['training_ready'] = all(
        {r['overtake_success'] for r in rows if r['dataset_split'] == split} == {0, 1}
        for split in ('train', 'validation', 'test'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows) if rows else pa.table({c: [] for c in dict.fromkeys(REQUIRED_COLUMNS)})
    temp = args.output.with_suffix('.partial')
    pq.write_table(table, temp, compression='zstd')
    temp.replace(args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temp_report = args.report.with_suffix('.partial')
    temp_report.write_text(json.dumps(report, indent=2) + '\n')
    temp_report.replace(args.report)
    print(f'Wrote {len(rows)} attempts; training_ready={report["training_ready"]}')


if __name__ == '__main__':
    main()
