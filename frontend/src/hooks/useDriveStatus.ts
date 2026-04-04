import { useState, useEffect } from 'react'
import { api } from '@/lib/api'

export function useDriveStatus() {
  const [data, setData] = useState<any>(null)

  useEffect(() => {
    const poll = () => api.getDriveStatus().then(setData).catch(() => {})
    poll()
    const id = setInterval(poll, 30000)
    return () => clearInterval(id)
  }, [])

  return data
}
