# Historical data downloader

Python 3.10+ on macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python scripts/download_openf1.py --year 2026 --driver 16
```

To download every available season for one driver, from 2023 through the
current year, run:

```sh
.venv/bin/python scripts/download_driver_history.py --driver 1
```

If a driver changes numbers, add a year-specific override. For Max Verstappen,
who uses 3 in 2026:

```sh
.venv/bin/python scripts/download_driver_history.py --driver 1 --driver-year 2026:3
```

Overrides are repeatable. Each year resolves the supplied number back to the
driver's name, preventing another driver who later uses the old number from
being written into the same driver folder.

The history runner also verifies identity automatically. It records the name
associated with the number in the first selected year. For each later year it
checks that identity, discovers and uses a changed number when present, and
stops if the original driver does not appear in any completed race that year.
This prevents a reassigned number from contaminating another driver's dataset.

The history runner invokes `download_openf1.py` once per year with
`--all-opponents`. Years and requests already completed are reused. If a year
fails, the runner stops; rerunning the same command resumes that year before
continuing to later seasons. Use `--start-year` or `--end-year` to narrow the
range.

No ingestion is performed by installing dependencies. Use `--session KEY` to
start with one race. `--all-opponents` additionally downloads all participating
drivers' telemetry, required for complete attacker/defender comparisons. Without
it the pilot contains the selected driver's telemetry and race-wide context;
it is not yet a complete training dataset. Opponents must not be selected only
from successful overtakes, which would omit failed opportunities.

Only non-cancelled `Race` sessions ending more than 30 minutes ago qualify.
Testing, practice, qualifying, sprints and future/live races are excluded.

## Data collected

| Dataset | Download scope | Modeling purpose |
|---|---|---|
| Sessions | Completed `Race` sessions for the requested year | Race discovery; excludes testing and other session types |
| Drivers | All participants in each selected race | Driver identity, number changes, teams, and opponent lookup |
| Meetings | One record per Grand Prix | Race and circuit metadata |
| Positions | Full selected race | Determine the adjacent attacker/defender and position changes |
| Overtakes | Full selected race | Confirm successful passes and create outcome labels |
| Intervals | API-filtered to gaps below 1 second; only gaps at or below the candidate threshold (normally 0.5 seconds) open telemetry windows | Detect plausible overtaking opportunities while retaining enough history to calculate closing rate |
| Laps | Selected driver and identified rivals | Lap number, same-lap validation, race phase, and lap context |
| Stints | Selected driver and identified rivals | Tyre compound and tyre age |
| Pit stops | Selected driver and identified rivals | Exclude pit-related position changes |
| Race control | Full selected race | Exclude yellow/red flags, safety cars, and VSC periods |
| Weather | Full selected race | Rainfall and track-condition features |
| Car data | Selected driver and relevant rival, only around candidate windows | Brake, throttle, speed, gear, RPM, and DRS features |
| Location | Selected driver and relevant rival, only after car telemetry confirms a credible attack or the Overtakes API confirms a pass | Physical braking position, distance, and corner clustering |
| Candidate windows | Derived locally | Merged time ranges eligible for telemetry retrieval |
| Same-lap overtakes | Derived locally | Removes passes involving lapped traffic |

Ctrl+C pauses. Rerun the identical command to resume or discover new races.
Completed requests are reused across drivers. No failed request is retried
automatically. A 404 for a bounded car/location telemetry window is stored as
an empty completed window. A 404 for optional event data (`intervals`, `laps`,
`stints`, `pit`, `overtakes`, `race_control`, or `weather`) is also stored as an
empty result. Catalog, driver, meeting, and position failures still stop the run.
429 responses trigger automatic exponential backoff: two minutes initially,
then progressively longer waits capped at 15 minutes. A longer server-provided
`Retry-After` value takes precedence. The same request resumes automatically.
Truncated responses, timeouts, and temporary connection failures retry up to
five times with waits increasing from 15 seconds to 2 minutes.
Successful empty responses are checkpointed as zero-row Parquet files.

Requests run serially at least 3 seconds apart (about 20/minute), leaving margin
below the 30/minute limit. This pacing is shared by catalog and dataset requests
within the process.
Avoid concurrent site/API use on the same IP while ingesting. One process per
output directory is allowed; separate directories still share OpenF1 limits.

Each driver/year run has its own folder:
`data/openf1/<name>/<year>/<session>/<endpoint>/<request-hash>.parquet`.
For example, driver 1 in 2025 is stored under
`data/openf1/max-verstappen/2025/`. The CLI and API data continue
to use driver numbers. `--output` changes the base directory while preserving
the driver/year hierarchy. Legacy `<name>-<year>` folders are automatically
moved into the new hierarchy when first encountered. Reusable name-resolution responses are kept under
`data/openf1/.catalog/`.

The manifest stores source URLs, timestamps, row counts, errors and progress.
Writes are atomic and partial files are not considered completed requests.
Raw overtakes remain untouched. Each session also contains
`derived/same_lap_overtakes.parquet`, which includes only events where lap data
places both drivers on the same lap. Events with different or unknown lap
numbers are excluded from this model-ready file.
The downloader retains interval samples within one second so preprocessing can
calculate closing rate. Only samples within `--max-gap` seconds (default 0.5)
create telemetry windows. It then uses positions to find moments involving the
selected driver and the adjacent car. Lap, stint and pit data is fetched only for the
selected driver and identified rivals; lapped-car and pit-lane windows are
excluded. Windows under yellow/red flags, safety cars, or virtual safety cars
are also excluded before telemetry is requested.
It first downloads car telemetry for the involved pair within
`--window-seconds` (default 15) before and after those moments. Location is
requested only when that telemetry contains sustained braking by both drivers,
the defender brakes no later than five seconds before the selected driver, and
the selected driver has at least a 20 km/h speed advantage. Successful same-lap
overtakes are always included even when they miss these gates. Closing-rate and
physical braking-distance rules still run during preprocessing because the
latter requires location data. The final qualified windows are stored in
`derived/candidate_windows.parquet`. Overlapping windows are merged; deduplicate
remaining boundary samples by session, driver and timestamp before training.
Older downloads may contain wider or rejected windows. This does not change the
modeling definition because preprocessing reapplies the final filters; it only
means those older folders contain extra raw telemetry.
All returned fields are preserved;
schemas may vary between files/years, so unify schemas when reading batches.
Timestamps remain source ISO strings. Brake is binary, not pressure.

Source: https://openf1.org/docs/

## Pooled race-centric acquisition

Use `download_openf1_pooled.py` for the all-driver model. It processes every
currently completed Grand Prix and Sprint from 2023 through the selected end year and
stores each race once under `data/openf1-pooled/<year>/<session_key>/`:

```sh
PYTHONPATH=scripts .venv/bin/python scripts/download_openf1_pooled.py \
  --start-year 2023 --end-year 2026
```

The pooled downloader discovers the session roster, so driver-number changes,
substitutions, arrivals, and departures require no special configuration.
Race-wide positions, overtakes, intervals, laps, stints, pits, race control,
and weather are requested once. Candidate windows are built for every adjacent
same-lap pair after lap one at gaps of 0.5 seconds or less. Overlapping telemetry ranges for
the same driver are merged before API calls. Car data is acquired first;
location is requested only for confirmed overtakes or windows containing the
required two-driver braking and 20 km/h speed-advantage signature.

Each completed race receives `derived/pooled_complete.json`; reruns skip it.
Individual requests also use the manifest and atomic Parquet checkpoints, so an
interrupted race resumes without repeating completed calls. HTTP 429 handling,
server-directed cooldowns, serial three-second request spacing, bounded network
retries, optional-endpoint 404 handling, and atomic writes are inherited from
the driver downloader. If a transient failure survives those retries, the
pooled runner waits five minutes and continues indefinitely. Permanent errors
still stop rather than silently creating an incomplete dataset. The active
2026 season includes only races ending at least 30 minutes before the run; rerun
later to append newly completed races.

### Acquisition gates and final model labels (pooled version 2)

| Decision | Where applied |
|---|---|
| Completed Grand Prix and Sprint only; no testing, practice, qualifying or Sprint Shootout | Session discovery |
| After lap one, adjacent car, same numbered lap, gap <=0.5s | Candidate discovery; known passes also create windows |
| Pit proximity and neutralized racing | Individual candidate moments before merging, and again at qualifying events |
| Sustained brake onset in both cars, defender onset 0–5s earlier, speed advantage >=20 km/h | Car-data gate for negative candidates; confirmed passes bypass this negative-only gate |
| Gap closing, within 0.5s at braking | Car-data stage using retained interval history |
| Closing rate >=0.02s/s OR positive physical braking distance | Final preprocessing after location is available |
| Braking separation <=100m, throttle-lift features, missing-feature flags | Final preprocessing |
| Same-opponent pass within 10s; duplicate attempts within 20s | Final preprocessing |

No minimum car speed is imposed. Location requests cover individual qualifying
events with 15 seconds of context on each side, merging overlaps per driver.
Rejected first-stage car samples remain as cached source data. Candidate windows
are not final training rows: pooled preprocessing must apply the remaining gates
and exclusions at each event, including within padded context.

Version 2 writes completion markers atomically and validates recorded Parquet
file sizes and row counts before skipping a race. Required driver, position,
lap and stint data must be nonempty; missing required data waits and retries
rather than recording completion. Successful empty overtake, filtered interval,
and race-control responses are valid (no passes, no close-running samples, or
no messages). These do not trigger retries; HTTP errors remain distinct and
are never interpreted as valid empty responses for these endpoints.
Weather/pit and bounded telemetry 404s still represent recorded empty responses;
completion means requests finished, not that every candidate has full telemetry.
Permanent HTTP errors (e.g. 401/403) stop with the error; transient errors retry.
A lock prevents two pooled runs writing the same output. Three-second pacing
and 429 backoff remain; independent downloaders/UI traffic are not coordinated.
Version 1 markers are re-evaluated and matching request caches are reused.
