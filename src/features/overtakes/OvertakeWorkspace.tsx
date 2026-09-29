import { useState } from 'react'
import type { Driver } from '../../api/openf1/types'
import { PassTelemetryChart } from './PassTelemetryChart'
import type { DriverBrakingOvertake } from './overtakeService'
import type { SessionKind } from './localOvertakeData'

type Props = { sessionName: SessionKind; driverNumber?: number; drivers: Driver[]; overtakes?: DriverBrakingOvertake[]; isLoading: boolean; error?: Error | null }
const eventKey = (event: DriverBrakingOvertake) => `${event.overtake.date}-${event.overtake.overtaking_driver_number}`

export function OvertakeWorkspace({ sessionName, driverNumber, drivers, overtakes, isLoading, error }: Props) {
  const [selectedKey, setSelectedKey] = useState<string>()
  const selectedDriver = drivers.find((driver) => driver.driver_number === driverNumber)
  const driverName = (number: number) => drivers.find((driver) => driver.driver_number === number)?.name_acronym ?? `#${number}`
  if (!driverNumber) return <section className="workspace empty-state">Choose a race and driver to inspect braking overtakes.</section>
  if (isLoading) return <section className="workspace empty-state">Loading local telemetry…</section>
  if (error) return <section className="workspace empty-state">Unable to load this analysis: {error.message}</section>
  const selected = overtakes?.find((event) => eventKey(event) === selectedKey) ?? overtakes?.[0]
  return <section className="workspace"><div className="workspace-heading"><div><p className="eyebrow">{sessionName} late-braking overtakes</p><h2>{selectedDriver?.full_name ?? `Driver #${driverNumber}`}</h2></div><strong>{overtakes?.length ?? 0} events</strong></div>{!overtakes?.length ? <p className="empty-state">No qualifying late-braking events found.</p> : <><PassTelemetryChart event={selected!} passerName={driverName(selected!.overtake.overtaking_driver_number)} defenderName={driverName(selected!.overtake.overtaken_driver_number)} /><div className="table-wrap"><table><thead><tr><th>Lap</th><th>Role</th><th>Opponent</th><th>Brake delay</th><th>Passer speed</th><th /></tr></thead><tbody>{overtakes.map((event) => { const passer = event.overtake.overtaking_driver_number; const opponent = event.selectedDriverRole === 'overtaking' ? event.overtake.overtaken_driver_number : passer; const isSelected = eventKey(event) === eventKey(selected!); return <tr key={eventKey(event)} className={isSelected ? 'selected-event' : ''}><td>{event.lapNumber ?? '—'}</td><td><span className={`role ${event.selectedDriverRole}`}>{event.selectedDriverRole === 'overtaking' ? 'Pass made' : 'Pass received'}</span></td><td>{driverName(opponent)}</td><td>+{(event.brakeOnsetAdvantageMs / 1_000).toFixed(2)}s</td><td>{event.overtakingBrakeOnset.speed} km/h</td><td><button className="trace-button" onClick={() => setSelectedKey(eventKey(event))}>View trace</button></td></tr> })}</tbody></table></div></>}</section>
}
