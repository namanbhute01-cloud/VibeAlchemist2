import { useState, useEffect } from 'react'
import { api } from '@/lib/api'

export interface Camera {
  id: number
  source: string
  status: string
  name: string
  feed_url: string
}

export function useCameras() {
  const [cameras, setCameras] = useState<Camera[]>([])

  useEffect(() => {
    const poll = () => {
      api.getCameras()
        .then(data => {
          const cams = Array.isArray(data) ? data : []
          setCameras(cams)
          console.log('[Cameras] Updated:', cams.length, 'cameras')
        })
        .catch(err => console.error('[Cameras] Poll error:', err))
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [])

  return cameras
}
