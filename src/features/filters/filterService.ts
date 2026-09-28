import { openF1Fetch } from '../../api/openf1/client'
import type { Driver, Meeting, Session } from '../../api/openf1/types'

/** Values for the Year → Race → Driver filter sequence. */
export async function getRacesForYear(year: number): Promise<Meeting[]> {
  const meetings = await openF1Fetch<Meeting[]>('meetings', new URLSearchParams({ year: String(year) }))
  return meetings.sort((a, b) => Date.parse(a.date_start) - Date.parse(b.date_start))
}

/** A Grand Prix can contain a Sprint as well, so select the canonical Race session explicitly. */
export async function getRaceSession(meetingKey: number): Promise<Session | undefined> {
  const sessions = await openF1Fetch<Session[]>('sessions', new URLSearchParams({
    meeting_key: String(meetingKey),
    session_name: 'Race',
  }))
  return sessions[0]
}

export async function getDriversForRace(sessionKey: number): Promise<Driver[]> {
  const drivers = await openF1Fetch<Driver[]>('drivers', new URLSearchParams({ session_key: String(sessionKey) }))
  return drivers.sort((a, b) => a.full_name.localeCompare(b.full_name))
}
