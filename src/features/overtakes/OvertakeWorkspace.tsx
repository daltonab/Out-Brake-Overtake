import type { Driver } from '../../api/openf1/types'
import type { DriverBrakingOvertake } from './overtakeService'

type Props = { driverNumber?: number; drivers: Driver[]; overtakes?: DriverBrakingOvertake[]; isLoading: boolean; error?: Error | null }

export function OvertakeWorkspace({ driverNumber, drivers, overtakes, isLoading, error }: Props) {
  const selectedDriver = drivers.find((driver) => driver.driver_number === driverNumber)
  const driverName = (number: number) => drivers.find((driver) => driver.driver_number === number)?.name_acronym ?? `#${number}`
  if (!driverNumber) return <section className="workspace empty-state">Choose a race and driver to inspect braking overtakes.</section>
  if (isLoading) return <section className="workspace empty-state">Analyzing telemetry…</section>
  if (error) return <section className="workspace empty-state">Unable to load this analysis: {error.message}</section>
  return <section className="workspace"><div className="workspace-heading"><div><p className="eyebrow">Late-braking overtakes</p><h2>{selectedDriver?.full_name ?? `Driver #${driverNumber}`}</h2></div><strong>{overtakes?.length ?? 0} events</strong></div>{!overtakes?.length ? <p className="empty-state">No qualifying late-braking events found.</p> : <div className="table-wrap"><table><thead><tr><th>Lap</th><th>Role</th><th>Opponent</th><th>Brake delay</th><th>Passer speed</th><th>Passer inputs</th><th>Overtaken @ passer brake</th></tr></thead><tbody>{overtakes.map((event) => { const passer = event.overtake.overtaking_driver_number; const opponent = event.selectedDriverRole === 'overtaking' ? event.overtake.overtaken_driver_number : passer; const passerInputs = event.overtakingBrakeOnset; const overtakenInputs = event.overtakenTelemetryAtPasserBrake ?? event.overtakenBrakeOnset; return <tr key={`${event.overtake.date}-${passer}`}><td>{event.lapNumber ?? '—'}</td><td><span className={`role ${event.selectedDriverRole}`}>{event.selectedDriverRole === 'overtaking' ? 'Pass made' : 'Pass received'}</span></td><td>{driverName(opponent)}</td><td>+{(event.brakeOnsetAdvantageMs / 1_000).toFixed(2)}s</td><td>{passerInputs.speed} km/h</td><td><InputBars brake={passerInputs.brake} throttle={passerInputs.throttle} /></td><td><InputBars brake={overtakenInputs.brake} throttle={overtakenInputs.throttle} /></td></tr> })}</tbody></table></div>}</section>
}

function InputBars({ brake, throttle }: { brake: number; throttle: number }) {
  return <div className="input-bars"><TelemetryBar value={brake} type="brake" /><TelemetryBar value={throttle} type="throttle" /></div>
}

function TelemetryBar({ value, type }: { value: number; type: 'brake' | 'throttle' }) {
  const percentage = Math.min(100, Math.max(0, value))
  return <div className={`telemetry-bar ${type}`} aria-label={`${type} ${percentage}%`}><span style={{ height: `${percentage}%` }} /><b>{percentage}%</b><small>{type === 'brake' ? 'B' : 'T'}</small></div>
}
