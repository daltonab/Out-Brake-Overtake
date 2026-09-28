"""Contract for one model-ready overtaking-attempt row."""

IDENTIFIERS = (
    'event_id', 'session_key', 'meeting_key', 'race_date', 'lap_number',
    'attacker_driver_number', 'defender_driver_number', 'brake_onset_at',
    'dataset_split', 'quality_flags',
)

NUMERIC_FEATURES = (
    'gap_seconds',
    'closing_rate_seconds_per_second',
    'attacker_speed_kph',
    'defender_speed_kph',
    'speed_delta_kph',
    'brake_onset_delta_seconds',
    'brake_distance_delta_m',
    'throttle_lift_delta_seconds',
    'attacker_tyre_age_laps',
    'defender_tyre_age_laps',
    'lap_fraction',
    'rainfall',
    'track_temperature_c',
)

CATEGORICAL_FEATURES = (
    'meeting_key',
    'corner_cluster',
    'attacker_compound',
    'defender_compound',
    'attacker_drs_active',
)

TARGET = 'overtake_success'
GROUP = 'session_key'

REQUIRED_COLUMNS = (*IDENTIFIERS, *NUMERIC_FEATURES, *CATEGORICAL_FEATURES, TARGET)


def validate_columns(columns):
    missing = sorted(set(REQUIRED_COLUMNS) - set(columns))
    if missing:
        raise ValueError(f'Model-ready dataset is missing columns: {", ".join(missing)}')
