import { useQuery } from '@tanstack/react-query'
import { getBrakingOvertakes, getBrakingOvertakesForDriver, type BrakingOvertakeOptions } from './overtakeService'

export function useBrakingOvertakes(sessionKey: number | undefined, options?: Partial<BrakingOvertakeOptions>) {
  return useQuery({
    queryKey: ['braking-overtakes', sessionKey, options],
    queryFn: () => getBrakingOvertakes(sessionKey!, options),
    enabled: sessionKey !== undefined,
  })
}

export function useDriverBrakingOvertakes(
  sessionKey: number | undefined,
  driverNumber: number | undefined,
  options?: Partial<BrakingOvertakeOptions>,
) {
  return useQuery({
    queryKey: ['braking-overtakes', sessionKey, driverNumber, options],
    queryFn: () => getBrakingOvertakesForDriver(sessionKey!, driverNumber!, options),
    enabled: sessionKey !== undefined && driverNumber !== undefined,
  })
}
