import type { Driver, Meeting, Session } from '../../api/openf1/types'

type ManifestDriver = Pick<Driver, 'driver_number' | 'full_name' | 'name_acronym' | 'team_name' | 'team_colour'>
export type SessionKind = 'Race' | 'Sprint'
type ManifestSession = { year: number; meeting_key: number; meeting_name: string; date_start: string; session_key: number; session_name: SessionKind; drivers: ManifestDriver[] }
type Manifest = { format_version: number; sessions: ManifestSession[] }
export type StaticTelemetry = { speed: number; brake: number; throttle: number }
export type TelemetryPoint = { t: number; speed: number; brake: number }
export type StaticOvertakeEvent = { date: string; overtaking_driver_number: number; overtaken_driver_number: number; lap_number?: number; brake_onset_advantage_ms: number; passer: StaticTelemetry; defender_at_passer_brake: StaticTelemetry; passer_brake_offset_ms: number; defender_brake_offset_ms: number; passer_trace: TelemetryPoint[]; defender_trace: TelemetryPoint[] }

let manifestRequest: Promise<Manifest> | undefined
const assetUrl = (path: string) => `${import.meta.env.BASE_URL}${path}`
async function manifest() {
  manifestRequest ??= fetch(assetUrl('overtakes/manifest.json')).then(async (response) => {
    if (!response.ok) throw new Error('The local overtake dataset is not available yet.')
    return response.json() as Promise<Manifest>
  })
  return manifestRequest
}

export async function getLocalRacesForYear(year: number, sessionKind: SessionKind): Promise<Meeting[]> {
  return (await manifest()).sessions.filter((session) => session.year === year && session.session_name === sessionKind).map(({ meeting_key, meeting_name, date_start, year: sessionYear }) => ({ meeting_key, meeting_name, date_start, year: sessionYear })).sort((a, b) => Date.parse(a.date_start) - Date.parse(b.date_start))
}

export async function getLocalRaceSession(meetingKey: number, sessionKind: SessionKind): Promise<Session | undefined> {
  const session = (await manifest()).sessions.find((entry) => entry.meeting_key === meetingKey && entry.session_name === sessionKind)
  return session && { meeting_key: session.meeting_key, session_key: session.session_key, session_name: session.session_name, session_type: session.session_name, date_start: session.date_start, year: session.year }
}

export async function getLocalDrivers(sessionKey: number): Promise<Driver[]> {
  const session = (await manifest()).sessions.find((entry) => entry.session_key === sessionKey)
  if (!session) return []
  return [...session.drivers].sort((a, b) => a.full_name.localeCompare(b.full_name)).map((driver) => ({ ...driver, meeting_key: session.meeting_key, session_key: session.session_key }))
}

export async function getLocalOvertakeEvents(sessionKey: number): Promise<StaticOvertakeEvent[]> {
  const response = await fetch(assetUrl(`overtakes/sessions/${sessionKey}.json`))
  if (!response.ok) throw new Error('The selected race is not available in the local overtake dataset.')
  return (await response.json() as { events: StaticOvertakeEvent[] }).events
}
