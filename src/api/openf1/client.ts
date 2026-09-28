const baseUrl = import.meta.env.VITE_OPENF1_API_URL ?? 'https://api.openf1.org/v1'
const responseCache = new Map<string, Promise<unknown>>()

export class OpenF1RequestError extends Error {
  constructor(readonly status: number) {
    super(`OpenF1 request failed: ${status}`)
  }
}

export async function openF1Fetch<T>(path: string, params?: URLSearchParams): Promise<T> {
  const url = new URL(`${baseUrl}/${path}`)
  params?.forEach((value, key) => url.searchParams.append(key, value))
  const cacheKey = url.toString()
  const cached = responseCache.get(cacheKey)
  if (cached) return cached as Promise<T>

  const request = fetch(url).then(async (response) => {
    if (!response.ok) throw new OpenF1RequestError(response.status)
    return response.json()
  })
  responseCache.set(cacheKey, request)
  try {
    return await request as T
  } catch (error) {
    responseCache.delete(cacheKey)
    throw error
  }
}
