const BASE = '/api'

/**
 * Create an abort signal with timeout — compatible with older browsers.
 * Falls back to AbortController + setTimeout if AbortSignal.timeout is unavailable.
 */
function createTimeoutSignal(ms: number): { signal: AbortSignal; cleanup: () => void } {
  // Try modern API first
  if (typeof AbortSignal.timeout === 'function') {
    return { signal: AbortSignal.timeout(ms), cleanup: () => {} };
  }
  // Fallback for older browsers
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  return {
    signal: controller.signal,
    cleanup: () => clearTimeout(timer),
  };
}

/**
 * Fetch with automatic retry (up to 2 retries with exponential backoff).
 * Prevents transient network errors from breaking the UI.
 */
async function fetchWithRetry(
  url: string,
  options?: RequestInit,
  retries = 2
): Promise<Response> {
  const { signal, cleanup } = createTimeoutSignal(5000);
  try {
    const response = await fetch(url, {
      ...options,
      signal,
    })
    return response
  } catch (err) {
    if (retries > 0) {
      await new Promise(r => setTimeout(r, 500))
      return fetchWithRetry(url, options, retries - 1)
    }
    throw err
  } finally {
    cleanup()
  }
}

async function jsonFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetchWithRetry(url, options)
  return res.json()
}

export const api = {
  // Cameras
  getCameras:          () => jsonFetch(`${BASE}/cameras`),
  getCameraConfig:     () => jsonFetch(`${BASE}/cameras/config`),
  saveCameraConfig:   (sources: string[]) =>
    jsonFetch(`${BASE}/cameras/config`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ sources }),
    }),
  setCameraSettings: (cam_id: number, settings: object) =>
    jsonFetch(`${BASE}/cameras/${cam_id}/settings`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(settings),
    }),

  // Settings / Config
  getSettings:         () => jsonFetch(`${BASE}/settings`),
  saveSettings:        (settings: Record<string, boolean | string | number>) =>
    jsonFetch(`${BASE}/settings`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ settings }),
    }),

  // Environment Variables
  getEnvVars:          () => jsonFetch(`${BASE}/settings/env-vars`),
  updateEnvVar:        (key: string, value: string) =>
    jsonFetch(`${BASE}/settings/env-vars`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ key, value }),
    }),
  updateSetting:       (key: string, value: boolean | string | number) =>
    jsonFetch(`${BASE}/settings/${key}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ value }),
    }),

  // Playback
  getPlayback:         () => jsonFetch(`${BASE}/playback/status`),
  getLibrary:          () => jsonFetch(`${BASE}/playback/library`),
  getDetailedLibrary:  () => jsonFetch(`${BASE}/playback/music/library`),
  addSong:             (file: File | null, group: string, url?: string) => {
    const formData = new FormData()
    if (file) formData.append('file', file)
    formData.append('group', group)
    if (url) formData.append('url', url)
    
    return fetch(`${BASE}/playback/add-song`, {
      method: 'POST',
      body: formData,
      signal: AbortSignal.timeout(60000),  // 60s for file uploads/downloads
    }).then(r => r.json())
  },
  downloadMusic: (url: string, group: string) =>
    jsonFetch(`${BASE}/playback/music/download`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url, group }),
      signal: AbortSignal.timeout(60000), // 60s for downloads
    }),
  // Simple Music Downloader (V6 Upgrade)
  getMusicLibrary: () => jsonFetch(`${BASE}/music/library`),
  downloadMusicSimple: (url: string) =>
    jsonFetch(`${BASE}/music/download`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url }),
      signal: AbortSignal.timeout(60000), // 60s for downloads
    }),
  playbackAction: (action: string, body?: object) =>
    jsonFetch(`${BASE}/playback/${action}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: body ? JSON.stringify(body) : undefined,
    }),

  // Vibe
  getVibeState:        () => jsonFetch(`${BASE}/vibe/current`),
  getVibeJournal:      () => jsonFetch(`${BASE}/vibe/journal`),

  // Faces
  getFaces:            () => jsonFetch(`${BASE}/faces`),

  // Drive
  getDriveStatus:      () => jsonFetch(`${BASE}/faces/drive/status`),

  // URLs
  feedUrl: (cam_id: number) => `/feed/${cam_id}`,
  wsUrl: () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/ws`
  },
}
