import { useState, useEffect, useRef } from 'react'
import { api } from '@/lib/api'

export interface Camera {
  id: number
  source: string
  status: string
  name: string
  feed_url: string
}

// Singleton pattern to prevent duplicate polling
let singletonState: Camera[] | null = null
let singletonListeners: Array<React.Dispatch<React.SetStateAction<Camera[]>>> = []

function notifyListeners(data: Camera[]) {
  singletonState = data
  singletonListeners.forEach(fn => fn(data))
}

export function useCameras() {
  const [cameras, setCameras] = useState<Camera[]>(singletonState || [])
  const prevRef = useRef<string | null>(null)

  useEffect(() => {
    singletonListeners.push(setCameras)

    // If we already have data, use it immediately
    if (singletonState && singletonState.length > 0) {
      setCameras(singletonState)
    }

    const poll = () => {
      api.getCameras()
        .then(data => {
          const cams = Array.isArray(data) ? data : []
          // Only update if data changed (stringify compare for deep equality)
          const key = JSON.stringify(cams)
          if (key !== prevRef.current) {
            prevRef.current = key
            notifyListeners(cams)
          }
        })
        .catch(err => console.error('[Cameras] Poll error:', err))
    }
    poll()
    const id = setInterval(poll, 3000)

    return () => {
      singletonListeners = singletonListeners.filter(l => l !== setCameras)
      clearInterval(id)
    }
  }, [])

  return cameras
}
