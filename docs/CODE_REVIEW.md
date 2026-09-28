# Project review — 2026-09-27

Scope: browser code, ingestion, preprocessing, modeling/export, tests, directory
layout, licensing, and future Git publication. No downloader, dataset, or running
process was moved or modified for this review. No repository was initialized.
This is a source review and local check, not a complete dependency security or
legal clearance audit.

## Open findings, ordered by impact

### P1: Prediction UI presents a placeholder as a trained probability

`src/pages/ModelPage.tsx` computes `likelihood` using a hard-coded arithmetic
formula and ignores the season/driver/tyre/DRS selections. It never loads
`public/models/max-verstappen.json`. Label or disable the prototype result until
real inference, feature validation, applicability limits, and export parity
tests are implemented. It is currently reachable from the Predictive Model tab.

### P1: Outcome-dependent sampling can inflate evaluation

`ml/src/prepare_data.py` applies the 0.5s/20km/h/closing-distance gate only to
failures. Successes can occur outside that support. Thus speed/gap can identify
the dataset selection rule instead of successful attacks. The pooled downloader
also deliberately preserves positives regardless of those gates. Keep the agreed
rules documented, but before claiming general probabilities evaluate a common
eligible population and sensitivity to thresholds. Balanced class weights also
mean probabilities require calibration checks on a representative holdout.

### P1: Browser braking logic differs from the model's rules

`src/features/overtakes/overtakeService.ts:firstBrake` selects the first pressed
sample, not a sustained off-to-on transition. There is no maximum onset delay,
same-lap check, pit exclusion or neutralization check. Brake application after
the pass can qualify because the window extends beyond it. This can display
ordinary, pit-related, or mismatched-corner passes as late-braking events.
Share specifications and test fixtures across implementations before claiming
the web analysis uses the same model definition. Brake is binary, not pressure.

### P1: Full-race web downloads remain unbounded in memory

`getRelevantTelemetry` requests whole-session car data for each rival, although
only short event windows are examined. `src/api/openf1/client.ts` holds response
promises forever, bypassing React Query's cache expiration. Changing drivers or
years can grow memory substantially; stale successful catalog results cannot
refresh. Use merged per-driver windows and a bounded cache or a single Query
cache. Request cancellation and a shared pacing mechanism are also missing;
the 400ms request spacing is local to one analysis invocation.

### P2: Closing-rate samples can refer to the wrong interval pair

`prepare_data.py` chooses the nearest interval (possibly after brake onset), but
finds the previous row relative to `brake_at`, not the chosen interval. If the
nearest sample is in the future, it skips the immediately preceding sample.
Adjacent-driver changes are not validated across these samples. Align to one
defined prediction timestamp and require opponent continuity. Nearest speed and
location also permit future samples, and coordinate scaling uses the full race;
these choices need an explicit retrospective-vs-live feature definition.

### P2: Repeated timeline work dominates pooled preprocessing (partly resolved)

`prepare_pooled.py` caches raw reads, but `build_session` rebuilds all drivers'
timelines, brake onsets and coordinate scale for every driver. `nearest` and
`value_at` rebuild timestamp lists on every lookup; brake detection repeatedly
scans whole timelines. Compute shared session state once, cache timestamp arrays,
and use bounded binary-search slices. Profile before replacing readable code.
Follow-up: shared timelines, all-driver brake detection and coordinate scaling
now run once per session using `prepare_session`; the pooled loop reuses its
read-only context. Timestamp-list lookup optimizations remain a separate option.

### P2: Completion is not proof of feature coverage

`scripts/download_openf1_pooled.py` treats bounded telemetry 404s as complete
empty requests and can wait indefinitely for unavailable required context.
Its completion marker validates files, not whether all features are available.
Retain coverage audits and separate unavailable sessions from healthy empty
events in a future recovery policy. Current acquisition still uses broad
neutralization state and conservative numbered-lap equality; these can exclude
valid data before preprocessing can recover it. Leave the active run untouched.

### P2: Training needs stronger split validation

`train_model.py` now defaults to a pooled model and intentionally excludes
driver identity and session type. It validates split labels and class presence
but does not assert weekend disjointness or unique event IDs. Add these
assertions, dataset hashes, preprocessing version, package versions, calibration
assessment and export-vs-sklearn prediction tests before training a publishable
pooled model. Do not tune against the existing test set repeatedly. Name-based
IDs need explicit alias handling if upstream spelling changes. The current
shuffled weekend split is appropriate for the agreed goal.

### P2: Release licensing and assets need distinct treatment

MIT now covers original code, per owner choice. OpenF1's upstream source license
is CC BY-NC-SA 4.0; that is not blanket clearance for data/model redistribution.
`THIRD_PARTY_NOTICES.md` records attribution and scope. The hero image's provenance
was clarified by the owner: it was AI-generated in another project chat.
That provenance is now recorded. Do not assert that
an MIT code license covers all assets and data.

### P2: Testing and dependency reproducibility are incomplete

The web test runner has no tests. Python has focused unit tests but no full
ingestion/preprocessing fixture that covers changing race control, unavailable
endpoints and same-lap boundary cases. Python dependencies use ranges without a
lock, and no unified Python lint/format configuration or CI exists. Add pinned
development environments, offline fixtures, lint/format checks, and CI after
establishing the intended support matrix. Avoid automatic formatting churn in
the running ingestion scripts. The old 429 test was fixed during this review:
it expected no retries and would otherwise hang indefinitely.

## Structure and hygiene completed

The current `src/`, `scripts/`, `ml/src/`, `public/`, and `data/` separation is
logical. No moves are needed. Updated README, MIT license/package metadata,
third-party notices, and exclusions for data, models, generated reports,
Parquet/Arrow files, Python/TypeScript caches, and editor artifacts. Raw-data
embedded telemetry reports under `ml/reports/` are local only. Small browser
model JSON is intentionally eligible for source control and needs release review.
An unused web function argument was removed to restore lint.

## Verification

Production build and lint passed after removing the unused parameter.
`npm test` reports no test files; this remains an open coverage issue. Python
unit suites passed all 18 tests, with mocked network calls and temporary files,
independent of the live downloader. Ignore rules passed 16 representative path
checks using the installed Git-ignore-compatible `ignore` library. The system
Git executable requires missing Apple developer tools, so actual Git staging
could not be tested. No Git initialization, commits, moves or API downloads
were performed by this review. Verify actual staging with Git once available;
ignore rules cannot protect force-added files or arbitrary custom output paths.
