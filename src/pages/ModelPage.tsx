import { useState } from 'react'
import { maxVerstappenModel, predictOvertake, type ScenarioValues } from '../features/model/logisticModel'

const initialScenario: ScenarioValues = { gap_seconds: 0.35, closing_rate_seconds_per_second: 0.03, attacker_speed_kph: 290, speed_delta_kph: 32, brake_onset_delta_seconds: 0.32, brake_distance_delta_m: 5.4, throttle_lift_delta_seconds: 0.24, attacker_tyre_age_laps: 7, defender_tyre_age_laps: 9, lap_fraction: 0.23, rainfall: 0, track_temperature_c: 36, attacker_compound: 'MEDIUM', defender_compound: 'MEDIUM', attacker_drs_active: true }

const numberInputs = [
  ['gap_seconds', 'Gap to car ahead', 's', 0.05, 1.5, 0.01], ['closing_rate_seconds_per_second', 'Gap closing rate', 's / s', 0, 0.1, 0.005], ['attacker_speed_kph', 'Entry speed', 'km/h', 150, 350, 1], ['speed_delta_kph', 'Speed advantage', 'km/h', -20, 80, 1], ['brake_onset_delta_seconds', 'Brake-onset advantage', 's', -0.5, 1, 0.01], ['brake_distance_delta_m', 'Braking-distance advantage', 'm', -30, 60, 1], ['throttle_lift_delta_seconds', 'Throttle-lift advantage', 's', -1, 2, 0.01], ['attacker_tyre_age_laps', 'Attacker tyre age', 'laps', 0, 40, 1], ['defender_tyre_age_laps', 'Defender tyre age', 'laps', 0, 40, 1], ['lap_fraction', 'Race progress', '%', 0, 1, 0.01], ['track_temperature_c', 'Track temperature', '°C', 5, 65, 1],
] as const

export function ModelPage() {
  const [scenario, setScenario] = useState<ScenarioValues>(initialScenario)
  const { probability, isLikely } = predictOvertake(scenario)
  const likelihood = Math.round(probability * 100)
  const setNumber = (feature: string, value: number) => setScenario((current) => ({ ...current, [feature]: value }))
  const setValue = (feature: string, value: string | boolean) => setScenario((current) => ({ ...current, [feature]: value }))

  return <section className="model-page">
    <div className="model-intro"><div><p className="eyebrow">Predictive modeling</p><h2>Build the passing scenario.</h2><p>Set the position an attacking driver needs before the braking zone. The probability below is calculated with the exported baseline logistic-regression model.</p></div><span className="model-badge">Max Verstappen baseline</span></div>
    <div className="model-layout model-layout-expanded"><section className="scenario-panel">
      <div className="scenario-selects"><label>Attacking tyre<select value={String(scenario.attacker_compound)} onChange={(event) => setValue('attacker_compound', event.target.value)}><option>HARD</option><option>MEDIUM</option><option>SOFT</option><option>INTERMEDIATE</option></select></label><label>Defending tyre<select value={String(scenario.defender_compound)} onChange={(event) => setValue('defender_compound', event.target.value)}><option>HARD</option><option>MEDIUM</option><option>SOFT</option><option>INTERMEDIATE</option></select></label><label>DRS on approach<select value={scenario.attacker_drs_active ? 'active' : 'inactive'} onChange={(event) => setValue('attacker_drs_active', event.target.value === 'active')}><option value="active">Active</option><option value="inactive">Inactive</option></select></label><label>Track condition<select value={scenario.rainfall ? 'wet' : 'dry'} onChange={(event) => setNumber('rainfall', event.target.value === 'wet' ? 1 : 0)}><option value="dry">Dry</option><option value="wet">Wet</option></select></label></div>
      <p className="eyebrow scenario-heading">Approach and braking zone</p><div className="scenario-input-grid">{numberInputs.map(([feature, label, unit, min, max, step]) => <ScenarioInput key={feature} label={label} unit={unit} min={min} max={max} step={step} current={Number(scenario[feature])} onChange={(value) => setNumber(feature, value)} />)}</div><div className="braking-definitions"><span><b>Brake-onset advantage</b> is timing: positive means the attacker begins braking later.</span><span><b>Braking-distance advantage</b> is position: positive means the attacker begins braking farther along the track.</span></div>
    </section><section className="prediction-panel"><p className="eyebrow">Model prediction</p><strong>{likelihood}<span>%</span></strong><h3>{isLikely ? 'Likely successful overtake' : 'Unlikely successful overtake'}</h3><div className="model-track"><span style={{ width: `${likelihood}%` }} /></div><p>{isLikely ? 'The modeled position clears the trained decision threshold.' : 'The modeled position is below the trained decision threshold.'}</p><div className="prediction-signals"><span>Decision threshold <b>{Math.round(maxVerstappenModel.decision_threshold * 100)}%</b></span><span>Gap target <b>{Number(scenario.gap_seconds) <= 0.4 ? 'within range' : 'close further'}</b></span><span>Brake timing <b>{Number(scenario.brake_onset_delta_seconds) >= 0.3 ? 'late enough' : 'brake later'}</b></span><span>Speed advantage <b>{Number(scenario.speed_delta_kph) >= 20 ? 'competitive' : 'build more'}</b></span></div><p className="model-footnote">Baseline only — trained on Max’s historical data using the current preprocessing rules.</p></section></div>
  </section>
}

function ScenarioInput({ label, unit, min, max, step, current, onChange }: { label: string; unit: string; min: number; max: number; step: number; current: number; onChange: (value: number) => void }) {
  const display = unit === '%' ? `${Math.round(current * 100)}%` : `${current.toFixed(step < 1 ? 2 : 0)} ${unit}`
  return <label className="scenario-input"><span>{label}<b>{display}</b></span><input type="range" min={min} max={max} step={step} value={current} onChange={(event) => onChange(Number(event.target.value))} /></label>
}
