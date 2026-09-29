import type { Driver, Meeting, Session } from '../../api/openf1/types'
import { getLocalDrivers, getLocalRaceSession, getLocalRacesForYear, type SessionKind } from '../overtakes/localOvertakeData'

/** Values for the Year → Race → Driver filter sequence. */
export async function getRacesForYear(year: number, sessionKind: SessionKind): Promise<Meeting[]> {
  return getLocalRacesForYear(year, sessionKind)
}

/** A Grand Prix can contain a Sprint as well, so select the canonical Race session explicitly. */
export async function getRaceSession(meetingKey: number, sessionKind: SessionKind): Promise<Session | undefined> {
  return getLocalRaceSession(meetingKey, sessionKind)
}

export async function getDriversForRace(sessionKey: number): Promise<Driver[]> {
  return getLocalDrivers(sessionKey)
}
