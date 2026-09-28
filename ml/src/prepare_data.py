"""Build one conservative model row per selected-driver overtaking attempt."""

import argparse
from bisect import bisect_right
from datetime import datetime, timezone
import math
from pathlib import Path
import random
from statistics import median

import pyarrow as pa
import pyarrow.parquet as pq

from schema import REQUIRED_COLUMNS


# Both outcomes use the same attack signature: within one second, a positive
# speed advantage, positive closing rate, matched braking, and the physical
# later-braking requirement below.  A completed same-opponent pass supplies
# the success label; an otherwise qualifying non-pass is a failure.
MIN_LATER_BRAKING_METRES = 5.0
MAX_BRAKING_SEPARATION_METRES = 100.0
LOCATION_MARGIN_METRES = 4.0  # Combined heuristic margin; not calibrated GPS accuracy.


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).timestamp()


def read_rows(directory):
    rows = []
    for path in sorted(directory.glob('*.parquet')):
        table = pq.read_table(path)
        if table.schema.names != ['_empty']:
            rows.extend(table.to_pylist())
    unique = {}
    for row in rows:
        key = tuple(sorted((key, str(value)) for key, value in row.items()))
        unique[key] = row
    return list(unique.values())


def timeline(rows, driver=None, date_field='date'):
    selected = [row for row in rows if row.get(date_field)
                and (driver is None or row.get('driver_number') == driver)]
    return sorted(((stamp(row[date_field]), row) for row in selected), key=lambda item: item[0])


def nearest(items, at, tolerance=3):
    if not items:
        return None
    times = [item[0] for item in items]
    index = bisect_right(times, at)
    choices = items[max(0, index - 1):index + 1]
    best = min(choices, key=lambda item: abs(item[0] - at))
    return best if abs(best[0] - at) <= tolerance else None


def value_at(items, at):
    times = [item[0] for item in items]
    index = bisect_right(times, at) - 1
    return items[index][1] if index >= 0 else None


def brake_onsets(items):
    result = []
    for index in range(1, len(items) - 1):
        at, row = items[index]
        if not row.get('brake') or items[index - 1][1].get('brake'):
            continue
        # Require two consecutive brake samples and one brake-free second beforehand.
        if not items[index + 1][1].get('brake'):
            continue
        prior = [sample for when, sample in items if at - 1 <= when < at]
        if prior and not any(sample.get('brake') for sample in prior):
            result.append((at, row))
    return result


def throttle_lift_before(items, brake_at, lookback=8):
    """Return the last sustained >=95% to <90% throttle transition before braking."""
    candidates = []
    for index in range(1, len(items) - 1):
        at, row = items[index]
        if not brake_at - lookback <= at <= brake_at:
            continue
        previous = items[index - 1][1].get('throttle')
        current = row.get('throttle')
        following = items[index + 1][1].get('throttle')
        if (previous is not None and current is not None and following is not None
                and previous >= 95 and current < 90 and following < 90):
            candidates.append(at)
    return candidates[-1] if candidates else None


def coordinate_scale(location_by_driver, car_by_driver):
    """Estimate OpenF1 coordinate units per metre from speed and sample movement."""
    ratios = []
    for driver, locations in location_by_driver.items():
        for (start, first), (end, second) in zip(locations, locations[1:]):
            elapsed = end - start
            if not 0.1 <= elapsed <= 1.5:
                continue
            car = nearest(car_by_driver.get(driver, []), (start + end) / 2, 1)
            speed = car[1].get('speed') if car else None
            if not isinstance(speed, (int, float)) or speed < 30:
                continue
            coordinate_distance = math.hypot(second['x'] - first['x'], second['y'] - first['y'])
            expected_metres = speed / 3.6 * elapsed
            if coordinate_distance > 0 and expected_metres > 0:
                ratios.append(coordinate_distance / expected_metres)
    return median(ratios) if ratios else None


def signed_braking_distance(attacker_locations, defender_locations,
                            attacker_at, defender_at, scale):
    """Project braking-point separation onto the attacker's local direction of travel."""
    if not scale:
        return None
    attacker = nearest(attacker_locations, attacker_at, 2)
    defender = nearest(defender_locations, defender_at, 2)
    before = nearest(attacker_locations, attacker_at - 0.6, 1)
    after = nearest(attacker_locations, attacker_at + 0.6, 1)
    if not all((attacker, defender, before, after)):
        return None
    dx = after[1]['x'] - before[1]['x']
    dy = after[1]['y'] - before[1]['y']
    length = math.hypot(dx, dy)
    if not length:
        return None
    separation_x = attacker[1]['x'] - defender[1]['x']
    separation_y = attacker[1]['y'] - defender[1]['y']
    return (separation_x * dx / length + separation_y * dy / length) / scale


def interpolated_position(items, at, max_gap=0.75):
    """Interpolate only within tightly bracketed location samples; never extrapolate."""
    index = bisect_right([t for t, _ in items], at)
    if index and items[index - 1][0] == at:
        row = items[index - 1][1]
        return row['x'], row['y']
    if index == 0 or index == len(items):
        return None
    (start, first), (end, last) = items[index - 1:index + 1]
    if not 0 < end - start <= max_gap:
        return None
    fraction = (at - start) / (end - start)
    return tuple(first[k] + fraction * (last[k] - first[k]) for k in ('x', 'y'))


def distance_evidence(attacker_locations, defender_locations, attacker_at,
                      defender_at, scale, attacker_off_at, defender_off_at):
    """Measure local along-track separation at the observed brake-on samples.

    The last-off/first-on intervals are retained as telemetry-quality checks.
    They are not treated as positional error bounds: doing so conflates normal
    distance travelled during an asynchronous braking decision with GPS error.
    """
    if not scale or not math.isfinite(scale) or scale <= 0:
        return None
    if not all(0 < on - off <= 0.75 for on, off in (
            (attacker_at, attacker_off_at), (defender_at, defender_off_at))):
        return None
    endpoints, directions = [], []
    for items, off, on in ((attacker_locations, attacker_off_at, attacker_at),
                            (defender_locations, defender_off_at, defender_at)):
        first, last = interpolated_position(items, off), interpolated_position(items, on)
        before = interpolated_position(items, off - 0.6)
        if first is None or last is None or before is None:
            return None
        dx, dy = last[0] - before[0], last[1] - before[1]
        length = math.hypot(dx, dy)
        if length <= 0:
            return None
        endpoints.append((first, last))
        directions.append((dx / length, dy / length))
    if sum(a * b for a, b in zip(*directions)) < math.cos(math.radians(30)):
        return None
    dx, dy = (sum(v[i] for v in directions) for i in (0, 1))
    norm = math.hypot(dx, dy)
    ux, uy = dx / norm, dy / norm
    def project(p):
        return (p[0] * ux + p[1] * uy) / scale
    attacker_points, defender_points = endpoints
    delta = (attacker_points[1][0] - defender_points[1][0],
             attacker_points[1][1] - defender_points[1][1])
    # Reject opposite/very different approaches and separation across the track.
    if abs(-delta[0] * uy + delta[1] * ux) / scale > 15:
        return None
    distance = project(attacker_points[1]) - project(defender_points[1])
    lower_bound = (min(map(project, attacker_points)) - max(map(project, defender_points))
                   - LOCATION_MARGIN_METRES)
    return {'distance_m': distance, 'lower_bound_m': lower_bound}


def lap_at(laps, at):
    row = value_at(laps, at)
    return row.get('lap_number') if row else None


def stint_at(stints, lap):
    if lap is None:
        return None
    # OpenF1 occasionally emits incomplete stint metadata. Missing boundaries
    # must not prevent otherwise valid telemetry rows from being processed.
    return next((row for row in stints
                 if row.get('lap_start') is not None
                 and row['lap_start'] <= lap <= (row.get('lap_end') or lap)), None)


def prepare_session(session_dir, reader=read_rows):
    """Compute shared session state once; callers must treat it as read-only."""
    read_rows = reader
    car = read_rows(session_dir / 'car_data')
    intervals_raw = read_rows(session_dir / 'intervals')
    positions_raw = read_rows(session_dir / 'position')
    overtakes_path = session_dir / 'derived' / 'same_lap_overtakes.parquet'
    overtakes = pq.read_table(overtakes_path).to_pylist() if overtakes_path.exists() else []
    laps_raw, stints_raw = read_rows(session_dir / 'laps'), read_rows(session_dir / 'stints')
    weather = timeline(read_rows(session_dir / 'weather'))
    locations_raw = read_rows(session_dir / 'location')
    drivers = sorted({row['driver_number'] for row in positions_raw})
    car_by_driver = {number: timeline(car, number) for number in drivers}
    position_by_driver = {number: timeline(positions_raw, number) for number in drivers}
    laps_by_driver = {number: timeline(laps_raw, number, 'date_start') for number in drivers}
    stints_by_driver = {number: [row for row in stints_raw if row.get('driver_number') == number]
                        for number in drivers}
    location_by_driver = {number: timeline(locations_raw, number) for number in drivers}
    brake_by_driver = {number: brake_onsets(car_by_driver[number]) for number in drivers}
    location_units_per_metre = coordinate_scale(location_by_driver, car_by_driver)
    total_laps = max((row.get('lap_number') or 0 for row in laps_raw), default=0)
    return {
        'session_dir': session_dir,
        'intervals_by_driver': {number: timeline(intervals_raw, number) for number in drivers},
        'drivers': drivers, 'overtakes': overtakes, 'weather': weather,
        'car_by_driver': car_by_driver, 'position_by_driver': position_by_driver,
        'laps_by_driver': laps_by_driver, 'stints_by_driver': stints_by_driver,
        'location_by_driver': location_by_driver, 'brake_by_driver': brake_by_driver,
        'location_units_per_metre': location_units_per_metre, 'total_laps': total_laps,
    }


def build_session(session_dir, driver, reader=read_rows, context=None):
    """Derive one driver's attempts, optionally reusing prepared session state."""
    context = prepare_session(session_dir, reader) if context is None else context
    if context['session_dir'] != session_dir:
        raise ValueError('Prepared context belongs to a different session')
    intervals = context['intervals_by_driver'].get(driver, [])
    drivers, overtakes, weather = context['drivers'], context['overtakes'], context['weather']
    car_by_driver = context['car_by_driver']
    position_by_driver = context['position_by_driver']
    laps_by_driver = context['laps_by_driver']
    stints_by_driver = context['stints_by_driver']
    location_by_driver = context['location_by_driver']
    brake_by_driver = context['brake_by_driver']
    location_units_per_metre = context['location_units_per_metre']
    total_laps = context['total_laps']
    interval_times = [item[0] for item in intervals]
    rows, ambiguous, last_attempt = [], 0, {}

    for at, attacker_car in brake_by_driver.get(driver, []):
        interval_sample = nearest(intervals, at, 4)
        attacker_position = value_at(position_by_driver.get(driver, []), at)
        if not interval_sample or not attacker_position or attacker_position.get('position', 1) <= 1:
            continue
        gap = interval_sample[1].get('interval')
        if not isinstance(gap, (int, float)) or not 0 < gap <= 1:
            continue
        target_position = attacker_position['position'] - 1
        defender = next((number for number in drivers
                         if (value_at(position_by_driver[number], at) or {}).get('position') == target_position), None)
        if defender is None:
            continue
        defender_brake = nearest(brake_by_driver.get(defender, []), at, 5)
        defender_car = nearest(car_by_driver.get(defender, []), at, 2)
        previous_index = bisect_right(interval_times, interval_sample[0]) - 2
        previous = intervals[previous_index] if previous_index >= 0 else None
        closing_rate = None
        if previous and 0 < interval_sample[0] - previous[0] <= 10:
            previous_gap = previous[1].get('interval')
            if isinstance(previous_gap, (int, float)):
                closing_rate = (previous_gap - gap) / (interval_sample[0] - previous[0])
        speed_delta = (attacker_car.get('speed') - defender_car[1].get('speed')) if (
            defender_car and attacker_car.get('speed') is not None
            and defender_car[1].get('speed') is not None) else None
        # Only confident attack signatures become positive/negative model rows.
        if defender_brake is None or closing_rate is None or closing_rate <= 0 or speed_delta is None or speed_delta <= 0:
            ambiguous += 1
            continue
        # A late-braking attack cannot use a defender brake event that happens
        # after the attacker's decision point; doing so would also leak future data.
        if defender_brake[0] > at:
            ambiguous += 1
            continue
        if at - last_attempt.get(defender, float('-inf')) < 20:
            continue
        success = any(row.get('overtaking_driver_number') == driver
                      and row.get('overtaken_driver_number') == defender
                      and 0 <= stamp(row['date']) - at <= 10 for row in overtakes)
        lap = lap_at(laps_by_driver.get(driver, []), at)
        if lap is None:
            ambiguous += 1
            continue
        attacker_stint = stint_at(stints_by_driver.get(driver, []), lap)
        defender_stint = stint_at(stints_by_driver.get(defender, []), lap)
        weather_row = (nearest(weather, at, 120) or (None, {}))[1]
        attacker_location = nearest(location_by_driver.get(driver, []), at, 2)
        attacker_lift = throttle_lift_before(car_by_driver.get(driver, []), at)
        defender_lift = throttle_lift_before(car_by_driver.get(defender, []), defender_brake[0])
        def preceding_off(items, on):
            index = bisect_right([t for t, _ in items], on) - 1
            return items[index - 1][0] if index > 0 else on
        evidence = distance_evidence(
            location_by_driver.get(driver, []), location_by_driver.get(defender, []),
            at, defender_brake[0], location_units_per_metre,
            preceding_off(car_by_driver[driver], at),
            preceding_off(car_by_driver[defender], defender_brake[0]))
        if (evidence is None or evidence['distance_m'] < MIN_LATER_BRAKING_METRES
                or evidence['distance_m'] > MAX_BRAKING_SEPARATION_METRES):
            ambiguous += 1
            continue
        brake_distance = evidence['distance_m']
        quality_flags = []
        if brake_distance is None:
            quality_flags.append('missing_brake_distance')
        if attacker_lift is None or defender_lift is None:
            quality_flags.append('missing_throttle_lift')
        if weather_row.get('track_temperature') is None:
            quality_flags.append('missing_weather')
        corner = None
        if attacker_location:
            corner = f"{round(attacker_location[1]['x'] / 1000)}:{round(attacker_location[1]['y'] / 1000)}"
        meeting = attacker_car.get('meeting_key')
        row = {column: None for column in REQUIRED_COLUMNS}
        row.update({
            'brake_distance_lower_bound_m': evidence['lower_bound_m'],
            'event_id': f'{session_dir.name}-{driver}-{defender}-{int(at * 1000)}',
            'session_key': int(session_dir.name), 'meeting_key': meeting,
            'race_date': datetime.fromtimestamp(at, timezone.utc).date().isoformat(),
            'lap_number': lap, 'attacker_driver_number': driver,
            'defender_driver_number': defender,
            # Preserve first-lap candidates for a dedicated audit. They are not
            # part of the default baseline because race-start dynamics are not
            # representative of normal braking-zone attacks.
            'lap_one_context': lap == 1,
            'model_eligible': lap != 1,
            'brake_onset_at': datetime.fromtimestamp(at, timezone.utc).isoformat(),
            'gap_seconds': gap, 'closing_rate_seconds_per_second': closing_rate,
            'attacker_speed_kph': attacker_car.get('speed'),
            'defender_speed_kph': defender_car[1].get('speed'),
            'speed_delta_kph': speed_delta,
            'brake_onset_delta_seconds': at - defender_brake[0],
            'brake_distance_delta_m': brake_distance,
            'throttle_lift_delta_seconds': (attacker_lift - defender_lift)
                                           if attacker_lift is not None and defender_lift is not None else None,
            'attacker_tyre_age_laps': ((attacker_stint or {}).get('tyre_age_at_start') or 0)
                                      + (lap - attacker_stint['lap_start'] if attacker_stint and lap else 0),
            'defender_tyre_age_laps': ((defender_stint or {}).get('tyre_age_at_start') or 0)
                                      + (lap - defender_stint['lap_start'] if defender_stint and lap else 0),
            'lap_fraction': lap / total_laps if total_laps else None,
            'rainfall': weather_row.get('rainfall'),
            'track_temperature_c': weather_row.get('track_temperature'),
            'corner_cluster': corner,
            'attacker_compound': (attacker_stint or {}).get('compound'),
            'defender_compound': (defender_stint or {}).get('compound'),
            'attacker_drs_active': bool((attacker_car.get('drs') or 0) >= 10),
            'overtake_success': int(success),
            'dataset_split': None, 'quality_flags': quality_flags,
        })
        rows.append(row)
        last_attempt[defender] = at
    return rows, ambiguous


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--driver', required=True, type=int)
    parser.add_argument('--driver-year', action='append', default=[], metavar='YEAR:NUMBER',
                        help='Override the driver number for one year')
    parser.add_argument('--session', action='append', type=int)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--split-seed', type=int, default=42,
                        help='Seed for reproducible race-level splitting')
    args = parser.parse_args()
    overrides = {}
    for value in args.driver_year:
        try:
            year, number = (int(part) for part in value.split(':', 1))
        except ValueError:
            parser.error('--driver-year must use YEAR:NUMBER, for example 2026:3')
        overrides[year] = number
    year_dirs = [path for path in args.input.iterdir()
                 if path.is_dir() and len(path.name) == 4 and path.name.isdigit()]
    session_jobs = []
    if year_dirs:
        for year_dir in sorted(year_dirs):
            number = overrides.get(int(year_dir.name), args.driver)
            for session in year_dir.iterdir():
                if session.is_dir() and session.name.isdigit():
                    session_jobs.append((session, number))
    else:
        sessions = [args.input / str(key) for key in args.session] if args.session else [
            path for path in args.input.iterdir() if path.is_dir() and path.name.isdigit()]
        session_jobs = [(session, args.driver) for session in sessions]
    rows, ambiguous = [], 0
    for session, number in sorted(session_jobs, key=lambda item: (str(item[0].parent), int(item[0].name))):
        if not (session / 'derived' / 'candidate_windows.parquet').exists():
            continue
        session_rows, session_ambiguous = build_session(session, number)
        rows.extend(session_rows); ambiguous += session_ambiguous
    split_by_session = {}
    sessions_by_year = {}
    for row in rows:
        year = int(row['race_date'][:4])
        session = sessions_by_year.setdefault(year, {}).setdefault(
            row['session_key'], {'successes': 0})
        session['successes'] += row['overtake_success']
    for year, session_stats in sorted(sessions_by_year.items()):
        rng = random.Random(args.split_seed + year)
        positive = sorted(key for key, value in session_stats.items() if value['successes'])
        negative = sorted(key for key, value in session_stats.items() if not value['successes'])
        rng.shuffle(positive); rng.shuffle(negative)
        count = len(session_stats)
        validation_count = max(1, round(count * 0.15)) if count >= 3 else 0
        test_count = max(1, round(count * 0.15)) if count >= 2 else 0
        train_count = count - validation_count - test_count
        if train_count < 1:
            train_count, validation_count = 1, max(0, count - 2)
            test_count = count - train_count - validation_count
        capacity = {'train': train_count, 'validation': validation_count, 'test': test_count}
        # When possible, seed every split with a race containing a success.
        for split in ('validation', 'test', 'train'):
            if positive and capacity[split]:
                split_by_session[positive.pop()] = split
                capacity[split] -= 1
        remaining = positive + negative
        rng.shuffle(remaining)
        for session_key in remaining:
            available = [split for split, slots in capacity.items() if slots]
            split = max(available, key=lambda name: capacity[name])
            split_by_session[session_key] = split
            capacity[split] -= 1
    for row in rows:
        row['dataset_split'] = split_by_session[row['session_key']]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), args.output, compression='zstd')
    successes = sum(row['overtake_success'] for row in rows)
    print(f'Wrote {len(rows)} attempts: {successes} successes, '
          f'{len(rows) - successes} failures; excluded {ambiguous} ambiguous braking events.')


if __name__ == '__main__':
    main()
