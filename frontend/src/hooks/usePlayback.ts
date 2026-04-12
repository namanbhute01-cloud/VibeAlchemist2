import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '@/lib/api'

export interface PlaybackStatus {
  song: string
  percent: number
  paused: boolean
  shuffle: boolean
  group: string
  volume: number
  playing: boolean
}

// ── Singleton: One shared poller for ALL components ──
// Prevents multiple instances from hammering the backend (was up to 10 req/s)
let sharedStatus: PlaybackStatus | null = null
const listeners = new Set<() => void>()
let pollInterval: ReturnType<typeof setInterval> | null = null
let activeListeners = 0

function notifyListeners() {
  listeners.forEach(fn => fn())
}

function startPolling() {
  if (pollInterval) return // Already polling

  const poll = async () => {
    try {
      const data = await api.getPlayback()
      sharedStatus = { ...data, playing: !data.paused }
      notifyListeners()
    } catch (err) {
      console.error('[Playback] Poll error:', err)
    }
  }

  poll()
  pollInterval = setInterval(poll, 1000) // 1 second — sufficient for music player
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

/**
 * Singleton playback hook — all components share ONE polling interval.
 * Reduces API requests from ~10/s (5 instances × 500ms) to ~1/s (1 shared poller).
 */
export function usePlayback() {
  const [status, setStatus] = useState<PlaybackStatus | null>(sharedStatus)
  const statusRef = useRef<PlaybackStatus | null>(sharedStatus)

  useEffect(() => {
    statusRef.current = status
  }, [status])

  // Register as listener and start/stop polling as needed
  useEffect(() => {
    activeListeners++
    if (activeListeners === 1) startPolling()

    const listener = () => setStatus(sharedStatus)
    listeners.add(listener)

    return () => {
      listeners.delete(listener)
      activeListeners--
      if (activeListeners === 0) stopPolling()
    }
  }, [])

  // Optimistic action helper
  const optimisticAction = useCallback((
    action: string,
    body?: object,
    optimisticUpdate?: (prev: PlaybackStatus) => PlaybackStatus
  ) => {
    if (optimisticUpdate && statusRef.current) {
      setStatus(prev => prev ? optimisticUpdate(prev) : prev)
    }

    api.playbackAction(action, body)
      .catch(err => {
        console.error(`[Playback] ${action} failed:`, err)
        // Revert on failure — refetch from server
        api.getPlayback().then(data => {
          sharedStatus = { ...data, playing: !data.paused }
          setStatus(sharedStatus)
        }).catch(() => {})
      })
  }, [])

  const actions = {
    pause: useCallback(() => {
      optimisticAction('pause', undefined, prev => ({
        ...prev, paused: true, playing: false
      }))
    }, [optimisticAction]),

    play: useCallback(() => {
      optimisticAction('play', undefined, prev => ({
        ...prev, paused: false, playing: true
      }))
    }, [optimisticAction]),

    next: useCallback((options?: { group?: string }) => {
      api.playbackAction('next', options).catch(console.error)
    }, []),

    prev: useCallback(() => {
      api.playbackAction('prev').catch(console.error)
    }, []),

    shuffle: useCallback(() => {
      optimisticAction('shuffle', undefined, prev => ({
        ...prev, shuffle: !prev.shuffle
      }))
    }, [optimisticAction]),

    setVol: useCallback((level: number) => {
      optimisticAction('volume', { level }, prev => ({
        ...prev, volume: level
      }))
    }, [optimisticAction]),

    mute: useCallback(() => {
      optimisticAction('mute', undefined, prev => ({
        ...prev, volume: 0
      }))
    }, [optimisticAction]),

    unmute: useCallback(() => {
      optimisticAction('unmute', undefined, prev => ({
        ...prev, volume: 70
      }))
    }, [optimisticAction]),

    // FIX: Add stop action — was missing from UI
    stop: useCallback(() => {
      optimisticAction('stop', undefined, prev => ({
        ...prev, paused: true, playing: false, song: 'None', percent: 0
      }))
    }, [optimisticAction]),
  }

  return {
    status,
    ...actions
  }
}
