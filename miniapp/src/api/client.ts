const BASE = '/api'

let _initDataRaw: string | null = null

export function setInitData(raw: string) {
  _initDataRaw = raw
}

export function getInitDataRaw(): string | null {
  return _initDataRaw
}

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (_initDataRaw) {
    headers['Authorization'] = `tma ${_initDataRaw}`
  }

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { ...headers, ...(options?.headers as Record<string, string>) },
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }

  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export { ApiError }

/** MF9: единое сообщение об ошибке API для всех страниц. */
export function apiErrorMessage(error: unknown): string {
  const msg = error instanceof Error ? error.message : String(error ?? '')
  if (msg.includes('401') || msg.includes('tma') || msg.includes('hash') || msg.includes('initData')) {
    return 'Откройте приложение через Telegram'
  }
  if (msg.includes('429')) return 'Слишком много запросов — попробуйте чуть позже'
  return msg || 'Что-то пошло не так'
}
