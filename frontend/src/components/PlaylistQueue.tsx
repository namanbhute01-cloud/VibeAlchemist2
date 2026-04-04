import { AnimatedCard } from "./AnimatedCard";
import { ListMusic, Play, Pause, MoreHorizontal, Music, Plus } from "lucide-react";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { usePlayback } from "@/hooks/usePlayback";
import { useVibeStream } from "@/hooks/useVibeStream";
import { cn } from "@/lib/utils";
import { useNavigate } from "react-router-dom";

interface Track {
  title: string;
  artist: string;
  group: string;
}

export function PlaylistQueue() {
  const navigate = useNavigate();
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const { status, pause, play, next } = usePlayback();
  const vibeState = useVibeStream();

  const handleAddTrack = () => {
    navigate('/playlist');
  };

  // Load library from backend
  useEffect(() => {
    const loadLibrary = () => {
      api.getLibrary()
        .then(lib => {
          const allTracks: Track[] = [];
          Object.entries(lib).forEach(([group, files]) => {
            (files as string[]).forEach((file, idx) => {
              allTracks.push({
                title: file.replace(/\.[^/.]+$/, ""),
                artist: group.charAt(0).toUpperCase() + group.slice(1),
                group: group
              });
            });
          });
          setTracks(allTracks.slice(0, 5)); // Show first 5 tracks
          setLoading(false);
        })
        .catch(err => {
          console.error('[PlaylistQueue] Load error:', err);
          setLoading(false);
        });
    };
    loadLibrary();
  }, []);

  const currentSong = vibeState?.current_song || status?.song || "None";
  const isPlaying = !(vibeState?.paused ?? status?.paused ?? true);

  const handlePlayTrack = (index: number) => {
    const track = tracks[index];
    if (track) {
      next({ group: track.group });
    }
  };

  if (loading) {
    return (
      <AnimatedCard delay={500}>
        <div className="flex items-center justify-center h-48">
          <p className="text-sm text-muted-foreground">Loading playlist...</p>
        </div>
      </AnimatedCard>
    );
  }

  if (tracks.length === 0) {
    return (
      <AnimatedCard delay={500}>
        <div className="flex items-center justify-center h-48 text-center">
          <div>
            <Music className="w-8 h-8 mx-auto mb-2 text-muted-foreground opacity-50" />
            <p className="text-sm text-muted-foreground">No tracks found</p>
            <p className="text-xs text-muted-foreground mt-1">Add music to OfflinePlayback folders</p>
          </div>
        </div>
      </AnimatedCard>
    );
  }

  return (
    <AnimatedCard delay={500}>
      <div className="flex items-center gap-2 mb-4">
        <ListMusic className="w-4 h-4 text-primary" />
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Up Next</p>
        <span className="ml-auto text-[10px] text-primary font-medium cursor-pointer hover:underline underline-offset-2 transition-colors hover:text-primary/80 active:scale-95 flex items-center gap-1">
          <button
            onClick={handleAddTrack}
            className="flex items-center gap-0.5 px-2 py-0.5 rounded bg-primary/10 hover:bg-primary/20 transition-colors"
          >
            <Plus className="w-3 h-3" /> Add
          </button>
          {tracks.length} tracks
        </span>
      </div>

      <div className="space-y-0.5">
        {tracks.map((track, i) => {
          const isCurrent = currentSong.includes(track.title);
          const isHovered = hoveredIndex === i;

          return (
            <div
              key={track.title}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 cursor-pointer group relative",
                isCurrent ? "bg-[hsl(var(--violet)/0.1)] border border-[hsl(var(--violet)/0.15)]" : "hover:bg-muted/50 border border-transparent",
              )}
              style={{
                animation: `float-in 0.5s cubic-bezier(0.16, 1, 0.3, 1) ${500 + i * 80}ms forwards`,
                opacity: 0,
              }}
              onClick={() => handlePlayTrack(i)}
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
            >
              {/* Number / Play / Pause / Waveform */}
              <div className="w-5 h-5 flex items-center justify-center shrink-0">
                {isCurrent && isPlaying ? (
                  <div className="flex items-end gap-[2px] h-3.5">
                    {[0, 1, 2].map(j => (
                      <div
                        key={j}
                        className="w-[3px] rounded-full bg-[hsl(var(--violet))]"
                        style={{
                          animation: `waveform 0.6s ease-in-out ${j * 0.15}s infinite`,
                          height: "4px",
                          transformOrigin: "bottom",
                        }}
                      />
                    ))}
                  </div>
                ) : isHovered ? (
                  <Play className="w-3.5 h-3.5 text-primary transition-transform duration-150 hover:scale-110" />
                ) : isCurrent ? (
                  <Pause className="w-3.5 h-3.5 text-primary" />
                ) : (
                  <span className="text-xs text-muted-foreground tabular-nums font-mono">{i + 1}</span>
                )}
              </div>

              <div className="flex-1 min-w-0">
                <p className={cn(
                  "text-sm font-medium truncate transition-colors duration-200",
                  isCurrent ? "text-[hsl(var(--violet))]" : "group-hover:text-foreground"
                )}>
                  {track.title}
                </p>
                <p className="text-[11px] text-muted-foreground truncate">{track.artist} Group</p>
              </div>

              <span className={cn(
                "text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-mono capitalize",
                isHovered ? "opacity-0" : "opacity-100"
              )}>
                {track.group}
              </span>
            </div>
          );
        })}
      </div>
    </AnimatedCard>
  );
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}
