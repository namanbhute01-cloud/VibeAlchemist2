import { useState, useEffect, useRef } from 'react'
import { api } from '@/lib/api'

export interface FaceStats {
  total_unique: number
  by_group: {
    kids: number
    youths: number
    adults: number
    seniors: number
  }
}

// Singleton pattern to prevent duplicate polling
let singletonState: FaceStats | null = null
let singletonListeners: Array<React.Dispatch<React.SetStateAction<FaceStats | null>>> = []

function notifyListeners(data: FaceStats) {
  singletonState = data
  singletonListeners.forEach(fn => fn(data))
}

export function useFaces(): FaceStats | null {
  const [data, setData] = useState<FaceStats | null>(singletonState)
  const prevRef = useRef<string | null>(null)

  useEffect(() => {
    singletonListeners.push(setData)

    // If we already have data, use it immediately
    if (singletonState) {
      setData(singletonState)
    }

    const poll = () => {
      api.getFaces()
        .then(faceData => {
          // Only update if data changed
          const key = JSON.stringify(faceData)
          if (key !== prevRef.current) {
            prevRef.current = key
            notifyListeners(faceData)
          }
        })
        .catch(err => console.error('[Faces] Poll error:', err))
    }
    poll()
    const id = setInterval(poll, 3000)

    return () => {
      singletonListeners = singletonListeners.filter(l => l !== setData)
      clearInterval(id)
    }
  }, [])

  return data
}
