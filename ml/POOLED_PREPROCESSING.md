# Pooled preprocessing

`src/prepare_pooled.py` consumes `data/openf1-pooled/<year>/<session>/`.
It reads only sessions with a completion marker and verifies its Parquet inventory.
In-progress sessions are skipped and recorded in the report. Raw downloads are
never modified; the downloader can continue while completed sessions are processed.

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/prepare_pooled.py
```

For a single-session audit, use separate outputs:

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/prepare_pooled.py --session 7953 \
  --output data/processed/pooled/bahrain-2023.parquet \
  --report ml/reports/pooled-bahrain-2023.json
```

## Steps and decisions

The shared [physical out-braking gate](PREPROCESSING.md#physical-out-braking-requirement-current-rule)
now applies to both outcomes before pooled exclusions: sufficient observed
along-track distance beyond the defender's braking point is mandatory, with
short sampled onset intervals required as a quality check. Missing evidence is
excluded. The shared implementation also emits `brake_distance_lower_bound_m`.

1. Reuse `prepare_data.build_session` for every roster member. Existing brake
   onset detection, gap/speed/closing gates, 10-second same-opponent success
   labels, approximate braking-distance calculation, 100m separation limit,
   20-second attempt deduplication, and feature extraction remain shared.
   The negative gate remains gap <=0.5s, speed advantage >=20km/h and either
   closing rate >=0.02s/s or positive braking-distance delta. No minimum speed.
   `prepare_data.prepare_session` reads and prepares driver timelines, brake
   onsets, and the session coordinate scale once. All drivers reuse this state;
   attempt rows and deduplication state remain separate per driver. Shared state
   is discarded when moving to the next session, bounding memory to one session.
2. Recheck that each row belongs to an acquired attacker/defender window.
   Exclude neutralized conditions at the event time and require known equal
   lap numbers for both drivers.
   Race-control replay tracks SC/VSC, red-flag suspension and sector yellows
   independently. Track-wide CLEAR/GREEN releases SC/VSC and sector yellows;
   red-flag suspension still requires `SESSION STARTED`. Local CLEAR applies
   only to its sector. Pit-exit lights and SC/VSC ending announcements do not
   restart racing. Rolling-start procedure messages retain neutralization
   until a track-wide release. This replay uses existing saved messages and
   requires no new API calls.
3. Exclude pit proximity using pit records. Additionally exclude a driver's
   entire pit-out lap and its preceding in-lap using `is_pit_out_lap`, for either
   car. This conservative fallback also works when the pit endpoint is empty.
   It sacrifices some valid on-track activity on those laps. Rows from sessions
   without pit records receive `pit_lap_fallback`; that flag is provenance,
   not a missing model feature. Unknown or inaccurate source flags cannot be
   reconstructed exactly. Numbered-lap equality is the existing conservative
   same-lap heuristic, including its start/finish-line limitation.
4. Normalize roster full names into stable IDs such as `max-verstappen`.
   Driver numbers are retained as source identifiers; name IDs are used across
   seasons. Fail on absent names or within-session identity collisions. Source
   spelling changes may require a future explicit alias mapping.
5. Add attacker/defender names and IDs, year, meeting key, and `session_name`
   (`Race` or `Sprint`). Lap-one candidates are retained with
   `lap_one_context=true` and `model_eligible=false` for a separate audit.
   Default training excludes them; do not train using the event ID or driver
   number.
6. Shuffle whole meeting keys within each year using seed 42. Approximately
   70/15/15 goes to train/validation/test. All drivers and both sessions from
   a weekend stay together. One available weekend goes to training only;
   two provide train/test. No outcome-based split tuning is performed. Adding
   weekends can change assignments; freeze the final dataset before evaluation.
7. Atomically write Parquet and a JSON audit with outcome counts, missing
   numerical features, quality flags, exclusions, skipped incomplete sessions,
   and breakdowns by driver, year, session type, and split. `training_ready`
   requires both outcomes in all three splits; it is not a statistical guarantee.

Default outputs: `data/processed/pooled/attempts.parquet` and
`ml/reports/pooled-preprocessing.json`. Rerunning rebuilds from all completed
sessions. Feature imputation/scaling must still be fitted on training data only.
The pooled trainer deliberately does not use driver identity: the initial model
is intended to generalize across the field. Sprint status is retained as audit
metadata; it is not yet a prediction feature.

The telemetry reviews linked in [PREPROCESSING.md](PREPROCESSING.md) explain the
shared attempt rules. These remain observational labels, with acquisition and
label-selection thresholds defining the population the model can describe.
