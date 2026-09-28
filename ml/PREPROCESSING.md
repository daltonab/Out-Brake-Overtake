# Preprocessing specification

The raw OpenF1 Parquet files are immutable inputs. `ml/src/prepare_data.py`
creates one model-ready row per confident overtaking attempt.

## Steps

### Physical out-braking requirement (current rule)

All successes and failures must now pass the same physical distance gate:
the attacker's braking point must be farther along the shared corner approach.
Timestamp delay alone no longer qualifies. Existing timing (0–5 seconds),
gap, closing-rate, and speed gates are retained; this change does not remove
the previously documented negative-only 20 km/h selection asymmetry.

- Interpolate location at the last brake-off and first brake-on samples for
  both drivers. No extrapolation; location brackets and off/on intervals must
  each be no wider than 0.75 seconds.
- Estimate each approach direction over the 0.6 seconds before its last off
  sample through its first on sample. Directions must agree within 30 degrees,
  and the braking points must be within 15m laterally. These are local geometric
  checks, not an official corner map or exact circuit arc-length calculation.
- Require short, tightly bracketed brake transitions (at most 0.75 seconds),
  then project the observed first-on points onto the mean approach direction
  using the existing per-session approximate coordinate-to-metre scale.
- Require observed first-on distance to be at least **5m**, and reject
  separation above **100m**. We retain the interval-based lower bound only as
  a diagnostic: using it as a hard gate incorrectly treats normal travel during
  asynchronous braking as location error.
- Missing/poor-quality/nonpositive/insufficient distance evidence is ambiguous
  and excluded even for API-confirmed passes. No failure label is manufactured.
- `brake_distance_delta_m` stores the decision quantity: first-on projected
  distance. `brake_distance_lower_bound_m` is diagnostic only and is not
  automatically added to training features.
- Only accepted events consume the existing 20-second deduplication interval.

This is stronger evidence of physical out-braking, not proof of driver intent
or causation. Curved approaches, alternate lines, approximate coordinates and
location/telemetry time alignment can still affect measurements. Sensitivity
analysis and plot review should precede treating the thresholds as validated.
Existing downloaded location/car data supports the rule; no new requests are
required. Rebuild processed datasets and models before using the new definition.

The initial five-session 2023 check retained 28 rows (7 successes, 21 failures),
versus 324 with the previous time-based eligibility. Output is saved separately
as `data/processed/pooled/sanity-2023-distance-rule.parquet`, with the report at
`ml/reports/sanity-2023-distance-rule.json`. This substantial reduction includes
missing/uncertain geometry, not just proven non-attacks. The sample is not
training-ready; inspect retained and rejected examples before tuning thresholds.

### Remaining pipeline

1. Read all endpoint files for each race, unify their rows, sort by UTC time,
   and remove exact duplicates.
2. Detect braking onset as a binary `0 -> 1` transition sustained for two
   telemetry samples after at least one brake-free second. No minimum speed is
   imposed, so low-speed corners remain eligible.
3. Require an attack signature: the selected driver is directly behind within
   one second, the gap is closing, the selected driver has a speed advantage,
   and both cars brake within five seconds of each other.
4. Retain lap-one candidates with `lap_one_context=true`, but mark them
   `model_eligible=false` so default training excludes race-start dynamics until
   a dedicated lap-one validation supports their inclusion. Exclude lapped
   traffic, pit-related windows, neutralized racing, duplicate attempts within
   20 seconds, and ambiguous close following. Also
   exclude cases where the defender brakes after the attacker and braking-point
   separations above 100 metres, which indicate future leakage or mismatched
   braking zones.
5. Label success only when the Overtakes endpoint records the selected driver
   passing the same defender within ten seconds after braking onset.
6. Treat an unconfirmed event as a failure only when the cars are within 0.5
   seconds, the attacker has at least a 20 km/h speed advantage, and either the
   gap is closing by at least 0.02 seconds per second or the attacker brakes
   farther along the circuit than the defender. Events that miss this stricter
   gate are ambiguous close-following and are excluded. This extra gate applies
   only to failures; API-confirmed successes must still satisfy the shared
   physical out-braking and quality requirements above.
7. Detect throttle lift as the final sustained transition from at least 95%
   throttle to below 90% within eight seconds before braking. Store the
   attacker's lift time minus the defender's.
8. Estimate location-coordinate scale for each race by comparing movement
   between location samples with speed-integrated metres. Use the interpolated
   onset intervals and shared approach direction described above; positive
   distance means the attacker braked farther along the local approach.
9. Derive tyre age and compound from the active stint, DRS from car telemetry,
   weather from the nearest sample, corner clusters from approximate coordinates,
   and race progress as current lap divided by the maximum completed race lap.
10. Record quality flags for missing braking distance, throttle lift, or weather.
   The audit reports these before a final feature-completeness policy is chosen.
11. Split complete races—not individual events—approximately 70% training, 15%
    validation, and 15% testing. Races are shuffled reproducibly within each
    year using seed 42, giving every split representation across the available
    seasons while preventing rows from one race crossing splits. When a year
    has at least three races containing successful attempts, one such race is
    seeded into each split before the remaining races are randomly assigned.

The resulting Parquet dataset contains identifiers, pre-attempt predictors,
the binary outcome, quality flags, and a deterministic race-level split.

## Review visualizations

- [Telemetry examples for successes and failures](reports/visualizations/overtake-telemetry-review.html)
- [Strong versus weak failed-attempt signatures](reports/visualizations/failed-attempt-review.html)

For a driver whose number changes, preprocess the complete history together so
the race splits remain globally chronological:

```sh
PYTHONPATH=ml/src .venv/bin/python ml/src/prepare_data.py \
  --input data/openf1/max-verstappen --driver 1 --driver-year 2026:3 \
  --output data/processed/max-verstappen/all-years.parquet
```
