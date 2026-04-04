import { useEffect, useState, useRef } from 'react'

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

export function useVibeStream(): VibeState | null {
  const [state, setState] = useState<VibeState | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(`/ws`)
      wsRef.current = ws
      
      ws.onopen = () => {
        console.log('[VibeStream] WebSocket connected')
      }
      
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          setState(data)
        } catch (err) {
          console.error('[VibeStream] Parse error:', err)
        }
      }
      
      ws.onclose = () => {
        console.log('[VibeStream] WebSocket closed. Reconnecting in 2s...')
        reconnectTimeoutRef.current = setTimeout(connect, 2000)
      }
      
      ws.onerror = (err) => {
        console.error('[VibeStream] Error:', err)
        ws.close()
      }
    }
    
    connect()
    
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      wsRef.current?.close()
    }
  }, [])

  return state
}
