import { useQuery } from '@tanstack/react-query'
import { getBrakingOvertakesForDriver } from './overtakeService'

export function useDriverBrakingOvertakes(
  sessionKey: number | undefined,
  driverNumber: number | undefined,
) {
  return useQuery({
    queryKey: ['local-braking-overtakes', sessionKey, driverNumber],
    queryFn: () => getBrakingOvertakesForDriver(sessionKey!, driverNumber!),
    enabled: sessionKey !== undefined && driverNumber !== undefined,
  })
}
