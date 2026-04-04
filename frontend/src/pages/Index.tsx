import { useState, useEffect } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { StatCard } from "@/components/StatCard";
import { CameraGrid } from "@/components/CameraGrid";
import { NowPlaying } from "@/components/NowPlaying";
import { AgeGauge } from "@/components/AgeGauge";
import { PlaylistQueue } from "@/components/PlaylistQueue";
import { LiveClock } from "@/components/LiveClock";
import { Camera, Users, Music, Activity, Flame, Plus } from "lucide-react";
import { useVibeStream } from "@/hooks/useVibeStream";
import { useCameras } from "@/hooks/useCameras";
import { useFaces } from "@/hooks/useFaces";
import { api } from "@/lib/api";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

const Dashboard = () => {
  const navigate = useNavigate();
  const vibeState = useVibeStream();
  const cameras = useCameras();
  const faceStats = useFaces() || { total_unique: 0, by_group: { kids: 0, youths: 0, adults: 0, seniors: 0 } };

  // Dynamic stats from VibeState (WebSocket) - primary source
  // Fallback to cameras hook and faces hook if WebSocket not connected
  const activeCams = vibeState?.active_cameras ?? cameras.length ?? 0;
  const uniqueFacesCount = vibeState?.unique_faces ?? faceStats.total_unique ?? 0;
  const currentVibe = vibeState?.current_vibe || 'Scanning...';
  const journalCount = vibeState?.journal_count || 0;
  const isPlaying = vibeState?.is_playing || false;
  const isPaused = vibeState?.paused || false;
  const currentSong = vibeState?.current_song || 'Idle';
  const avgAge = vibeState?.age || '...';

  const handleAddTrack = () => {
    navigate('/playlist');
    toast.info("Navigate to Playlist", { description: "Add songs from the Playlist page" });
  };

  const ageBreakdown = [
    { range: "Kids", count: faceStats.by_group?.kids || 0, color: "hsl(43 96% 56%)" },
    { range: "Youths", count: faceStats.by_group?.youths || 0, color: "hsl(173 58% 39%)" },
    { range: "Adults", count: faceStats.by_group?.adults || 0, color: "hsl(262 52% 62%)" },
    { range: "Seniors", count: faceStats.by_group?.seniors || 0, color: "hsl(346 72% 58%)" },
  ];

  // Debug logging
  useEffect(() => {
    console.log('[Dashboard] vibeState:', vibeState);
    console.log('[Dashboard] cameras:', cameras.length);
    console.log('[Dashboard] faceStats:', faceStats);
  }, [vibeState, cameras, faceStats]);

  return (
    <DashboardLayout>
      <div className="max-w-7xl mx-auto space-y-8 pb-24">
        {/* Header */}
        <div className="flex items-end justify-between gap-4 pb-2 border-b border-white/5">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Flame className="w-5 h-5 text-primary" />
              <span className="text-xs font-bold text-primary uppercase tracking-[0.2em]">Real-time Alchemy</span>
            </div>
            <h1 className="text-4xl font-black tracking-tighter text-white">VIBE ALCHEMIST</h1>
            <p className="text-sm text-muted-foreground mt-1 font-medium opacity-60">
              Intelligent ambiance active for {activeCams} sources
            </p>
          </div>
          <LiveClock />
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard icon={Camera} label="Active Cameras" value={activeCams} sub="Streams Online" delay={100} trend="neutral" color="teal" />
          <StatCard icon={Users} label="Unique Faces" value={uniqueFacesCount} sub="Across all time" delay={160} trend="up" color="rose" />
          <StatCard icon={Activity} label="Current Vibe" value={currentVibe.toUpperCase()} sub={`${journalCount} events logged`} delay={220} glow trend="neutral" color="amber" />
          <StatCard icon={Music} label="Music Status" value={isPlaying ? (isPaused ? "PAUSED" : "PLAYING") : "IDLE"} sub={currentSong} delay={280} trend="up" color="violet" />
        </div>

        {/* Main grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <div className="flex items-center gap-3">
              <h2 className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Live Vision Grid</h2>
              <div className="flex-1 h-px bg-white/5" />
            </div>
            <CameraGrid />
          </div>

          <div className="space-y-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Ambiance Engine</h2>
              <button
                onClick={handleAddTrack}
                className="flex items-center gap-1 px-2 py-1 rounded-md bg-primary/10 text-primary text-xs hover:bg-primary/20 transition-colors"
              >
                <Plus className="w-3 h-3" /> Add Track
              </button>
              <div className="flex-1 h-px bg-white/5" />
            </div>
            <NowPlaying />
            <AgeGauge avgAge={avgAge} ageBreakdown={ageBreakdown} delay={450} />
            <PlaylistQueue />
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
};

export default Dashboard;
