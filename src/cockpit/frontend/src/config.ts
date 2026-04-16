const DEFAULT_API_PORT = import.meta.env.VITE_COCKPIT_API_PORT?.trim() || '7777'

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '')
}

export function resolveApiBase(): string {
  const configuredBase = import.meta.env.VITE_COCKPIT_API_BASE?.trim()
  if (configuredBase) {
    return trimTrailingSlash(configuredBase)
  }

  if (typeof window === 'undefined') {
    return `http://127.0.0.1:${DEFAULT_API_PORT}`
  }

  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:'
  const host = window.location.hostname || '127.0.0.1'
  return `${protocol}//${host}:${DEFAULT_API_PORT}`
}

export function resolveWsUrl(apiBase: string): string {
  const url = new URL('/ws/state', `${trimTrailingSlash(apiBase)}/`)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}
