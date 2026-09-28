"""Run download_openf1.py sequentially for every available OpenF1 season."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

from download_openf1 import Downloader, completed_races


FIRST_OPENF1_YEAR = 2023


def driver_year(value):
    try:
        year_text, number_text = value.split(':', 1)
        year, number = int(year_text), int(number_text)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError('Use YEAR:DRIVER_NUMBER, for example 2026:3.')
    if number < 1:
        raise argparse.ArgumentTypeError('Driver numbers must be positive.')
    return year, number


def normalized_name(row):
    name = row.get('full_name') or row.get('broadcast_name')
    return ' '.join(name.casefold().split()) if name else None


def completed_year_races(catalog, year):
    sessions = catalog.get('sessions', {'year': year, 'session_name': 'Race'})
    return sorted(completed_races(sessions, datetime.now(timezone.utc)),
                  key=lambda row: row['date_start'], reverse=True)


def establish_identity(catalog, year, number):
    races = completed_year_races(catalog, year)
    if not races:
        raise SystemExit(f'No completed races are available for {year}.')
    for race in races:
        drivers = catalog.get('drivers', {'session_key': race['session_key']})
        match = next((row for row in drivers if row.get('driver_number') == number), None)
        if match and normalized_name(match):
            return normalized_name(match), match.get('full_name') or match.get('broadcast_name')
    raise SystemExit(f'Driver number {number} was not found in any completed {year} race.')


def number_for_identity(catalog, year, identity, preferred_number, display_name):
    races = completed_year_races(catalog, year)
    if not races:
        raise SystemExit(f'No completed races are available for {year}; stopping at {display_name}.')
    seen_wrong_name = None
    for race in races:
        drivers = catalog.get('drivers', {'session_key': race['session_key']})
        preferred = next((row for row in drivers
                          if row.get('driver_number') == preferred_number), None)
        if preferred and normalized_name(preferred) == identity:
            return preferred_number
        if preferred:
            seen_wrong_name = preferred.get('full_name') or preferred.get('broadcast_name')
        match = next((row for row in drivers if normalized_name(row) == identity), None)
        if match:
            discovered = match['driver_number']
            print(f'{display_name} uses driver number {discovered} in {year}; '
                  f'switching from {preferred_number}.', flush=True)
            return discovered
    detail = (f' Number {preferred_number} belongs to {seen_wrong_name}.'
              if seen_wrong_name else '')
    raise SystemExit(f'{display_name} was not found in any completed {year} race.{detail}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', required=True, type=int,
                        help='Season-specific driver number')
    parser.add_argument('--start-year', type=int, default=FIRST_OPENF1_YEAR)
    parser.add_argument('--end-year', type=int,
                        default=datetime.now(timezone.utc).year)
    parser.add_argument('--driver-year', action='append', type=driver_year, default=[],
                        metavar='YEAR:NUMBER',
                        help='Override the driver number for one year; repeatable')
    parser.add_argument('--output', type=Path, default=Path('data/openf1'))
    parser.add_argument('--max-gap', type=float, default=0.5)
    parser.add_argument('--window-seconds', type=int, default=15)
    args = parser.parse_args()

    current_year = datetime.now(timezone.utc).year
    if (args.driver < 1 or args.start_year < FIRST_OPENF1_YEAR
            or args.end_year > current_year or args.start_year > args.end_year):
        parser.error(f'Use a positive driver number and years from '
                     f'{FIRST_OPENF1_YEAR} through {current_year}.')
    overrides = {}
    for year, number in args.driver_year:
        if not args.start_year <= year <= args.end_year:
            parser.error(f'Driver override year {year} is outside the selected range.')
        if year in overrides:
            parser.error(f'Driver number for {year} was specified more than once.')
        overrides[year] = number

    downloader = Path(__file__).with_name('download_openf1.py')
    catalog = Downloader(args.output / '.catalog')
    identity, display_name = establish_identity(
        catalog, args.start_year, overrides.get(args.start_year, args.driver))
    years = range(args.start_year, args.end_year + 1)
    for year in years:
        preferred_number = overrides.get(year, args.driver)
        number = number_for_identity(catalog, year, identity, preferred_number, display_name)
        command = [
            sys.executable, str(downloader),
            '--year', str(year),
            '--driver', str(number),
            '--all-opponents',
            '--output', str(args.output),
            '--max-gap', str(args.max_gap),
            '--window-seconds', str(args.window_seconds),
        ]
        print(f'\n=== Downloading driver {number}, season {year} ===', flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise SystemExit(
                f'Season {year} stopped with exit code {result.returncode}. '
                'Rerun this command to resume; completed requests and years will be reused.')
        print(f'=== Season {year} complete ===', flush=True)

    print(f'\nAll available seasons ({args.start_year}-{args.end_year}) are complete.')


if __name__ == '__main__':
    main()
