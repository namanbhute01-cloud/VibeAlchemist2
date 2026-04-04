import { DashboardLayout } from "@/components/DashboardLayout";
import { CameraGrid } from "@/components/CameraGrid";
import { Camera } from "lucide-react";
import { useCameras } from "@/hooks/useCameras";
import { useVibeStream } from "@/hooks/useVibeStream";

export default function CamerasPage() {
  const cameras = useCameras();
  const vibeState = useVibeStream();

  const isLoading = cameras === null || cameras === undefined;
  const activeCams = cameras?.length ?? 0;
  const totalPeople = vibeState?.journal_count || 0;
  const liveCount = cameras?.filter(c => c.status === "online").length ?? 0;

  return (
    <DashboardLayout>
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-end justify-between gap-4 pb-2 border-b border-border/30" style={{ animation: "float-in 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards" }}>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Camera className="w-5 h-5 text-[hsl(var(--info))]" />
              <span className="text-xs font-medium text-[hsl(var(--info))] uppercase tracking-widest">Surveillance Grid</span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight">Camera Feeds</h1>
            <p className="text-sm text-muted-foreground mt-1">Live monitoring across all {activeCams} zones</p>
          </div>
          <div className="flex items-center gap-6 text-sm">
            <div className="text-center">
              <p className="text-2xl font-bold text-[hsl(var(--info))]">{isLoading ? "..." : liveCount}</p>
              <p className="text-[10px] text-muted-foreground uppercase tracking-widest">Live</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-[hsl(var(--rose))]">{totalPeople}</p>
              <p className="text-[10px] text-muted-foreground uppercase tracking-widest">Unique Faces</p>
            </div>
          </div>
        </div>

        <div className="pt-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-24">
              <div className="text-center space-y-3">
                <div className="w-8 h-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin mx-auto" />
                <p className="text-sm text-muted-foreground">Loading camera feeds...</p>
              </div>
            </div>
          ) : (
            <CameraGrid />
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
