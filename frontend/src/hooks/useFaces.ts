import { useState, useEffect } from 'react'
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

export function useFaces(): FaceStats | null {
  const [data, setData] = useState<FaceStats | null>(null)

  useEffect(() => {
    const poll = () => {
      api.getFaces()
        .then(faceData => {
          setData(faceData)
          console.log('[Faces] Updated:', faceData)
        })
        .catch(err => console.error('[Faces] Poll error:', err))
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [])

  return data
}
