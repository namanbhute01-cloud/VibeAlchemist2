import { useEffect, useState, useRef, useCallback } from 'react'

export interface VibeState {
  status: string
  detected_group: string
  current_vibe: string
  age: string
  average_age: number
  journal_count: number
  percent_pos: number
  is_playing: boolean
  paused: boolean
  shuffle: boolean
  current_song: string
  next_vibe: string | null
  active_cameras: number
  unique_faces: number
}

export interface DetectionEvent {
  id: string
  group: string
  age: number
  cam_id: number
  timestamp: number
}

export interface VibeStreamData {
  vibe: VibeState
  detections: DetectionEvent[]
  connected: boolean
}

// ═══════════════════════════════════════════════════════════
// SINGLETON WebSocket — one connection shared by all components
// FIX: Prevents 8+ simultaneous WS connections hammering backend
// ═══════════════════════════════════════════════════════════

let singletonWs: WebSocket | null = null
let singletonState: VibeState | null = null
let listeners: Set<(state: VibeState | null) => void> = new Set()
let reconnectTimer: NodeJS.Timeout | null = null

function connect() {
  if (singletonWs && (singletonWs.readyState === WebSocket.CONNECTING || singletonWs.readyState === WebSocket.OPEN)) {
    return // Already connected or connecting
  }

  if (singletonWs) {
    singletonWs.onclose = null // Prevent reconnection loop from old socket
    singletonWs.close()
  }

  const ws = new WebSocket(`/ws`)
  singletonWs = ws

  ws.onopen = () => {
    console.log('[VibeStream] WebSocket connected')
  }

  ws.onmessage = (e) => {
    try {
      const data: VibeState = JSON.parse(e.data)
      // Only update if data actually changed (shallow comparison)
      const prev = singletonState
      if (!prev) {
        singletonState = data
      } else {
        const keys = Object.keys(data) as (keyof VibeState)[]
        const changed = keys.some(k => prev[k] !== data[k])
        if (changed) {
          singletonState = data
        }
      }
      // Notify all listeners
      listeners.forEach(cb => cb(singletonState))
    } catch (err) {
      console.error('[VibeStream] Parse error:', err)
    }
  }

  ws.onclose = () => {
    console.log('[VibeStream] WebSocket closed. Reconnecting in 2s...')
    singletonWs = null
    singletonState = null
    listeners.forEach(cb => cb(null))
    reconnectTimer = setTimeout(connect, 2000)
  }

  ws.onerror = (err) => {
    console.error('[VibeStream] Error:', err)
    ws.close() // Triggers onclose → reconnect
  }
}

function cleanup() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (singletonWs) {
    singletonWs.onclose = null
    singletonWs.close()
    singletonWs = null
    singletonState = null
  }
  listeners.clear()
}

// ── React hook using singleton ──
export function useVibeStream(): VibeState | null {
  const [state, setState] = useState<VibeState | null>(singletonState)

  useEffect(() => {
    // Start singleton connection if not running
    if (listeners.size === 0) {
      connect()
    }

    // Register listener
    listeners.add(setState)

    return () => {
      // Remove listener
      listeners.delete(setState)
      // Clean up only if no listeners remain (e.g. unmount last component)
      if (listeners.size === 0) {
        cleanup()
      }
    }
  }, [])

  return state
}

// ── Non-hook accessor for components that need current state without subscribing ──
export function getVibeStreamState(): VibeState | null {
  return singletonState
}

// ── Force reconnect (e.g. after settings change) ──
export function reconnectVibeStream() {
  cleanup()
  connect()
}
