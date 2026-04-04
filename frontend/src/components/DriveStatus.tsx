import { useDriveStatus } from '@/hooks/useDriveStatus'
import { Badge } from '@/components/ui/badge'
import { Cloud, CloudOff, RefreshCw } from 'lucide-react'

export function DriveStatus() {
  const data = useDriveStatus()

  if (!data) return null

  return (
    <div className="flex items-center gap-3 bg-white/5 border border-white/10 px-3 py-1.5 rounded-full backdrop-blur-sm">
      <div className="flex items-center gap-2">
        {data.connected ? (
          <Cloud className="w-3.5 h-3.5 text-emerald-400" />
        ) : (
          <CloudOff className="w-3.5 h-3.5 text-muted-foreground" />
        )}
        <span className="text-[10px] font-semibold uppercase tracking-widest text-white/70">
          {data.connected ? 'Cloud Active' : 'Local Only'}
        </span>
      </div>
      
      <div className="w-px h-3 bg-white/10" />
      
      <div className="flex items-center gap-2">
        <RefreshCw className="w-3 h-3 text-muted-foreground" />
        <span className="text-[10px] text-muted-foreground font-mono">
          {data.pending_count > 0 ? `${data.pending_count} pending` : 'Synced'}
        </span>
      </div>
    </div>
  )
}
