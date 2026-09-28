import { OpenF1RequestError, openF1Fetch } from '../../api/openf1/client'
import type { CarData, Lap, Overtake } from '../../api/openf1/types'

export type BrakingOvertake = {
  overtake: Overtake
  overtakingTelemetry: CarData[]
  overtakenTelemetry: CarData[]
  overtakingBrakeOnset: CarData
  overtakenBrakeOnset: CarData
  overtakenTelemetryAtPasserBrake: CarData
  brakeOnsetAdvantageMs: number
  lapNumber?: number
}

export type DriverBrakingOvertake = BrakingOvertake & {
  selectedDriverRole: 'overtaking' | 'overtaken'
}

export type BrakingOvertakeOptions = {
  /** Seconds of telemetry to examine before an overtake is recorded. */
  preOvertakeWindowSeconds: number
  /** Seconds to retain after an overtake is recorded. */
  postOvertakeWindowSeconds: number
  /** OpenF1 reports brake as 0 or 100; this remains configurable for robustness. */
  brakeThreshold: number
  /** Minimum delay in the overtaker's braking onset versus the overtaken driver. */
  minimumLateBrakeMs: number
}

const defaults: BrakingOvertakeOptions = {
  preOvertakeWindowSeconds: 8,
  postOvertakeWindowSeconds: 2,
  brakeThreshold: 1,
  minimumLateBrakeMs: 250,
}

/**
 * Returns overtakes whose telemetry supports a late-braking explanation.
 *
 * OpenF1 records an overtake when the position exchange is complete, not at
 * brake application. We therefore inspect the preceding telemetry window and
 * require both drivers to brake, with the overtaker braking later.
 */
export async function getBrakingOvertakes(
  sessionKey: number,
  options: Partial<BrakingOvertakeOptions> = {},
): Promise<BrakingOvertake[]> {
  const settings = { ...defaults, ...options }
  const overtakes = await getOvertakes(sessionKey)
  const telemetry = await getRelevantTelemetry(overtakes)
  return toBrakingOvertakes(overtakes, telemetry, settings)
}

/**
 * Gets every late-braking candidate involving a driver, including passes made
 * against that driver. The braking metric always describes the passing driver.
 */
export async function getBrakingOvertakesForDriver(
  sessionKey: number,
  driverNumber: number,
  options: Partial<BrakingOvertakeOptions> = {},
): Promise<DriverBrakingOvertake[]> {
  const settings = { ...defaults, ...options }
  const overtakes = (await getOvertakes(sessionKey)).filter(
    (overtake) => overtake.overtaking_driver_number === driverNumber || overtake.overtaken_driver_number === driverNumber,
  )
  const telemetry = await getRelevantTelemetry(overtakes)

  const brakingOvertakes = toBrakingOvertakes(overtakes, telemetry, settings)
  const lapNumbers = await getLapNumbers(brakingOvertakes)
  return brakingOvertakes.map((overtake) => ({
    ...overtake,
    lapNumber: lapNumbers.get(overtake.overtake),
    selectedDriverRole: overtake.overtake.overtaking_driver_number === driverNumber ? 'overtaking' : 'overtaken',
  }))
}

async function getOvertakes(sessionKey: number): Promise<Overtake[]> {
  return openF1Fetch<Overtake[]>('overtakes', new URLSearchParams({ session_key: String(sessionKey) }))
}

function toBrakingOvertakes(
  overtakes: Overtake[],
  telemetry: Map<number, CarData[]>,
  settings: BrakingOvertakeOptions,
): BrakingOvertake[] {
  return overtakes.flatMap((overtake) => {
    const eventTime = Date.parse(overtake.date)
    const start = eventTime - settings.preOvertakeWindowSeconds * 1_000
    const end = eventTime + settings.postOvertakeWindowSeconds * 1_000
    const overtakingTelemetry = telemetryForEvent(telemetry, overtake.overtaking_driver_number, start, end)
    const overtakenTelemetry = telemetryForEvent(telemetry, overtake.overtaken_driver_number, start, end)
    const overtakingBrakeOnset = firstBrake(overtakingTelemetry, settings.brakeThreshold)
    const overtakenBrakeOnset = firstBrake(overtakenTelemetry, settings.brakeThreshold)

    if (!overtakingBrakeOnset || !overtakenBrakeOnset) return []
    const brakeOnsetAdvantageMs = Date.parse(overtakingBrakeOnset.date) - Date.parse(overtakenBrakeOnset.date)
    if (brakeOnsetAdvantageMs < settings.minimumLateBrakeMs) return []

    const overtakenTelemetryAtPasserBrake = nearestSample(overtakenTelemetry, overtakingBrakeOnset.date)
    return [{ overtake, overtakingTelemetry, overtakenTelemetry, overtakingBrakeOnset, overtakenBrakeOnset, overtakenTelemetryAtPasserBrake, brakeOnsetAdvantageMs }]
  })
}

async function getRelevantTelemetry(
  overtakes: Overtake[],
): Promise<Map<number, CarData[]>> {
  if (overtakes.length === 0) return new Map()
  const sessionKey = overtakes[0].session_key
  const driverNumbers = [...new Set(overtakes.flatMap((overtake) => [overtake.overtaking_driver_number, overtake.overtaken_driver_number]))]
  const entries = await mapWithConcurrency(driverNumbers, 2, async (driverNumber) => {
    const parameters = new URLSearchParams({
      session_key: String(sessionKey),
      driver_number: String(driverNumber),
    })
    const data = await carDataOrEmpty(parameters)
    return [driverNumber, data] as const
  })
  const telemetry = new Map<number, CarData[]>()
  for (const [driverNumber, samples] of entries) {
    telemetry.set(driverNumber, [...(telemetry.get(driverNumber) ?? []), ...samples])
  }
  return telemetry
}

async function carDataOrEmpty(parameters: URLSearchParams): Promise<CarData[]> {
  try {
    return await openF1Fetch<CarData[]>('car_data', parameters)
  } catch (error) {
    if (error instanceof OpenF1RequestError && error.status === 404) return []
    throw error
  }
}

async function getLapNumbers(overtakes: BrakingOvertake[]): Promise<Map<Overtake, number | undefined>> {
  const sessionKey = overtakes[0]?.overtake.session_key
  if (!sessionKey) return new Map()
  const laps = await lapsOrEmpty(new URLSearchParams({ session_key: String(sessionKey) }))
  const lapsByDriver = new Map<number, Lap[]>()
  for (const lap of laps) lapsByDriver.set(lap.driver_number, [...(lapsByDriver.get(lap.driver_number) ?? []), lap])
  for (const driverLaps of lapsByDriver.values()) driverLaps.sort((a, b) => Date.parse(a.date_start) - Date.parse(b.date_start))
  return new Map(overtakes.map((event) => [event.overtake, lapAt(lapsByDriver.get(event.overtake.overtaking_driver_number) ?? [], event.overtake.date)]))
}

async function lapsOrEmpty(parameters: URLSearchParams): Promise<Lap[]> {
  try {
    return await openF1Fetch<Lap[]>('laps', parameters)
  } catch {
    // Lap numbers enhance the table but should never invalidate a completed
    // telemetry analysis when OpenF1 temporarily rate-limits this extra call.
    return []
  }
}

function lapAt(laps: Lap[], date: string): number | undefined {
  const eventTime = Date.parse(date)
  return laps.reduce<Lap | undefined>((latest, lap) => Date.parse(lap.date_start) <= eventTime ? lap : latest, undefined)?.lap_number
}

function telemetryForEvent(telemetry: Map<number, CarData[]>, driverNumber: number, start: number, end: number): CarData[] {
  return (telemetry.get(driverNumber) ?? []).filter((sample) => {
    const timestamp = Date.parse(sample.date)
    return timestamp >= start && timestamp <= end
  })
}

function firstBrake(samples: CarData[], threshold: number): CarData | undefined {
  return samples.find((sample) => sample.brake >= threshold)
}

function nearestSample(samples: CarData[], targetDate: string): CarData {
  const target = Date.parse(targetDate)
  return samples.reduce((nearest, sample) => Math.abs(Date.parse(sample.date) - target) < Math.abs(Date.parse(nearest.date) - target) ? sample : nearest)
}

async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  mapper: (item: T) => Promise<R>,
): Promise<R[]> {
  const results: R[] = []
  let nextIndex = 0
  let lastRequestStartedAt = 0
  const worker = async () => {
    while (nextIndex < items.length) {
      const index = nextIndex++
      const waitMs = Math.max(0, 400 - (Date.now() - lastRequestStartedAt))
      if (waitMs) await new Promise((resolve) => setTimeout(resolve, waitMs))
      lastRequestStartedAt = Date.now()
      results[index] = await mapper(items[index])
    }
  }
  await Promise.all(Array.from({ length: Math.min(1, limit, items.length) }, worker))
  return results
}
