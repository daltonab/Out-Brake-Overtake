import type { Driver, Meeting, Session } from '../../api/openf1/types'
import { getLocalDrivers, getLocalRaceSession, getLocalRacesForYear } from '../overtakes/localOvertakeData'

/** Values for the Year → Race → Driver filter sequence. */
export async function getRacesForYear(year: number): Promise<Meeting[]> {
  return getLocalRacesForYear(year)
}

/** A Grand Prix can contain a Sprint as well, so select the canonical Race session explicitly. */
export async function getRaceSession(meetingKey: number): Promise<Session | undefined> {
  return getLocalRaceSession(meetingKey)
}

export async function getDriversForRace(sessionKey: number): Promise<Driver[]> {
  return getLocalDrivers(sessionKey)
}
