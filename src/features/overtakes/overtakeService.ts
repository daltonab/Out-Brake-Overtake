import { getLocalOvertakeEvents, type StaticTelemetry, type TelemetryPoint } from './localOvertakeData'

export type DriverBrakingOvertake = {
  overtake: { date: string; overtaking_driver_number: number; overtaken_driver_number: number }
  overtakingBrakeOnset: StaticTelemetry
  overtakenTelemetryAtPasserBrake: StaticTelemetry
  brakeOnsetAdvantageMs: number
  passerBrakeOffsetMs: number
  defenderBrakeOffsetMs: number
  passerTrace: TelemetryPoint[]
  defenderTrace: TelemetryPoint[]
  lapNumber?: number
  selectedDriverRole: 'overtaking' | 'overtaken'
}

export async function getBrakingOvertakesForDriver(sessionKey: number, driverNumber: number): Promise<DriverBrakingOvertake[]> {
  const events = await getLocalOvertakeEvents(sessionKey)
  return events.flatMap((event) => {
    if (event.overtaking_driver_number !== driverNumber && event.overtaken_driver_number !== driverNumber) return []
    return [{
      overtake: { date: event.date, overtaking_driver_number: event.overtaking_driver_number, overtaken_driver_number: event.overtaken_driver_number },
      overtakingBrakeOnset: event.passer,
      overtakenTelemetryAtPasserBrake: event.defender_at_passer_brake,
      brakeOnsetAdvantageMs: event.brake_onset_advantage_ms,
      passerBrakeOffsetMs: event.passer_brake_offset_ms,
      defenderBrakeOffsetMs: event.defender_brake_offset_ms,
      passerTrace: event.passer_trace,
      defenderTrace: event.defender_trace,
      lapNumber: event.lap_number,
      selectedDriverRole: event.overtaking_driver_number === driverNumber ? 'overtaking' : 'overtaken',
    }]
  })
}
