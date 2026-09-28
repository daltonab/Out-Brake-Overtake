import type { Driver, Meeting } from '../../api/openf1/types'

type Props = { year: number; raceKey?: number; driverNumber?: number; races: Meeting[]; drivers: Driver[]; disabled?: boolean; onYearChange: (year: number) => void; onRaceChange: (meetingKey: number) => void; onDriverChange: (driverNumber: number) => void }
const years = [2026, 2025, 2024, 2023]

export function AnalysisFilters({ year, raceKey, driverNumber, races, drivers, disabled, onYearChange, onRaceChange, onDriverChange }: Props) {
  return <section aria-label="Analysis filters" className="filters-panel">
    <label><span>Season</span><select value={year} onChange={(e) => onYearChange(Number(e.target.value))}>{years.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
    <label><span>Grand Prix</span><select value={raceKey ?? ''} disabled={!races.length} onChange={(e) => onRaceChange(Number(e.target.value))}><option value="">Select race</option>{races.map((race) => <option key={race.meeting_key} value={race.meeting_key}>{race.meeting_name}</option>)}</select></label>
    <label><span>Driver</span><select value={driverNumber ?? ''} disabled={!drivers.length || disabled} onChange={(e) => onDriverChange(Number(e.target.value))}><option value="">Select driver</option>{drivers.map((driver) => <option key={driver.driver_number} value={driver.driver_number}>{driver.full_name} · {driver.team_name}</option>)}</select></label>
  </section>
}
