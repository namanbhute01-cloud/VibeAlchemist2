import { useCameras } from '@/hooks/useCameras'
import { api } from '@/lib/api'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Users, Eye, RefreshCw } from 'lucide-react'
import { useState, useEffect } from 'react'

export function CameraGrid() {
  const cameras = useCameras()
  const [feedErrors, setFeedErrors] = useState<Record<number, number>>({})
  // FIX: Store cache-buster timestamp per camera, only update on error recovery
  const [feedKeys, setFeedKeys] = useState<Record<number, number>>({})

  // Auto-retry: increment error counter periodically to trigger img reload
  useEffect(() => {
    if (Object.keys(feedErrors).length === 0) return
    const interval = setInterval(() => {
      setFeedErrors(prev => {
        const updated: Record<number, number> = {}
        for (const [k, v] of Object.entries(prev)) {
          if (v < 3) updated[Number(k)] = v + 1
        }
        return updated
      })
    }, 10000) // Increased from 5s to 10s to reduce flickering
    return () => clearInterval(interval)
  }, [feedErrors])

  if (cameras.length === 0) {
    return (
      <Card className="flex items-center justify-center h-48 text-muted-foreground border-dashed">
        No cameras connected. Add CAMERA_SOURCES to the backend .env file.
      </Card>
    )
  }

  return (
    <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(320px,1fr))', gap:16}}>
      {cameras.map(cam => {
        const errorCount = feedErrors[cam.id] || 0
        const hasError = errorCount > 0
        const imgKey = `${cam.id}-${errorCount}`
        
        // FIX: Only add cache-buster when recovering from error, not on every render
        const feedUrl = hasError 
          ? `${api.feedUrl(cam.id)}?retry=${Date.now()}`
          : api.feedUrl(cam.id)
        
        // FIX: Update feed key when recovering from error to force reload
        useEffect(() => {
          if (hasError && errorCount > 0) {
            setFeedKeys(prev => ({ ...prev, [cam.id]: Date.now() }))
          }
        }, [errorCount])

        return (
          <Card key={cam.id} className="overflow-hidden bg-black/40 border-white/5 backdrop-blur-md">
            <div className="relative aspect-video bg-black">
              <img
                key={imgKey}
                src={feedUrl}
                className={`w-full h-full object-contain ${hasError ? 'opacity-30' : ''}`}
                // FIX: Add loading="eager" and decoding="sync" for lowest latency
                loading="eager"
                decoding="sync"
                onError={() => {
                  setFeedErrors(prev => ({ ...prev, [cam.id]: (prev[cam.id] || 0) + 1 }))
                }}
              />

              {/* Error overlay with reconnecting indicator */}
              {hasError && errorCount >= 3 && (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground bg-black/60">
                  <RefreshCw className="w-8 h-8 mb-2 opacity-50 animate-spin" />
                  <p className="text-xs">Feed unavailable</p>
                  <p className="text-[10px] opacity-50 mt-1">Will retry automatically</p>
                </div>
              )}

              {/* Live indicator */}
              <div className="absolute top-3 left-3 flex items-center gap-1.5 bg-red-500/20 backdrop-blur-sm px-2 py-1 rounded border border-red-500/30">
                <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
                <span className="text-[9px] font-medium text-red-400 uppercase tracking-wider">LIVE</span>
              </div>

              {/* Auto-enhancement indicator */}
              <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-emerald-500/20 backdrop-blur-sm px-2 py-1 rounded border border-emerald-500/30">
                <Eye className="w-3 h-3 text-emerald-400" />
                <span className="text-[9px] font-medium text-emerald-400 uppercase tracking-wider">AI Enhanced</span>
              </div>

              {/* Camera name overlay */}
              <div className="absolute bottom-3 left-3 flex items-center gap-2 bg-black/60 backdrop-blur-sm px-2 py-1 rounded border border-white/10">
                <Users className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-xs font-medium text-white">{cam.name}</span>
              </div>
            </div>
            <div className="p-3 flex items-center justify-between">
              <span className="text-sm font-medium text-white/80">Camera Feed</span>
              <Badge variant={cam.status === 'online' ? 'default' : 'secondary'} className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">
                {cam.status === 'online' ? 'Online' : 'Offline'}
              </Badge>
            </div>
          </Card>
        )
      })}
    </div>
  )
}
