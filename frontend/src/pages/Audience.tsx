import { DashboardLayout } from "@/components/DashboardLayout";
import { AnimatedCard } from "@/components/AnimatedCard";
import { Users, TrendingUp, TrendingDown, Clock, UserCheck, BarChart3 } from "lucide-react";
import { useState, useEffect } from "react";
import { useVibeStream } from "@/hooks/useVibeStream";
import { useFaces } from "@/hooks/useFaces";
import { api } from "@/lib/api";

export default function AudiencePage() {
  const vibeState = useVibeStream();
  const faceStats = useFaces();
  const [journal, setJournal] = useState<any>(null);

  // Poll vibe journal
  useEffect(() => {
    const poll = () => {
      api.getVibeJournal()
        .then(setJournal)
        .catch(err => console.error('[Audience] Journal poll error:', err));
    };
    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, []);

  const isLoading = faceStats === null || faceStats === undefined;
  const totalUnique = faceStats?.total_unique ?? vibeState?.journal_count ?? 0;
  const vibeJournalCount = journal?.count ?? vibeState?.journal_count ?? 0;

  const ageGroups = [
    { range: "Kids", count: faceStats?.by_group?.kids ?? 0, color: "hsl(43 96% 56%)" },
    { range: "Youths", count: faceStats?.by_group?.youths ?? 0, color: "hsl(173 58% 39%)" },
    { range: "Adults", count: faceStats?.by_group?.adults ?? 0, color: "hsl(262 52% 62%)" },
    { range: "Seniors", count: faceStats?.by_group?.seniors ?? 0, color: "hsl(346 72% 58%)" },
  ];

  const totalFaces = totalUnique || 1;

  return (
    <DashboardLayout>
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-end justify-between gap-4 pb-2 border-b border-border/30" style={{ animation: "float-in 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards" }}>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Users className="w-5 h-5 text-[hsl(var(--rose))]" />
              <span className="text-xs font-medium text-[hsl(var(--rose))] uppercase tracking-widest">Audience Analytics</span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight">Audience</h1>
            <p className="text-sm text-muted-foreground mt-1">Demographics & real-time crowd intelligence</p>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <AnimatedCard delay={100}>
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-[hsl(var(--rose))/0.1] flex items-center justify-center">
                <Users className="w-6 h-6 text-[hsl(var(--rose))]" />
              </div>
              <div>
                <p className="text-3xl font-bold">{isLoading ? "..." : totalUnique}</p>
                <p className="text-xs text-muted-foreground uppercase">Unique Identities</p>
              </div>
            </div>
          </AnimatedCard>
          <AnimatedCard delay={180}>
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center">
                <UserCheck className="w-6 h-6 text-primary" />
              </div>
              <div>
                <p className="text-3xl font-bold">{vibeJournalCount}</p>
                <p className="text-xs text-muted-foreground uppercase">Vibe Journal Events</p>
              </div>
            </div>
          </AnimatedCard>
          <AnimatedCard delay={260}>
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-[hsl(var(--violet))/0.1] flex items-center justify-center">
                <Clock className="w-6 h-6 text-[hsl(var(--violet))]" />
              </div>
              <div>
                <p className="text-3xl font-bold">LIVE</p>
                <p className="text-xs text-muted-foreground uppercase">Real-time Stream</p>
              </div>
            </div>
          </AnimatedCard>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Vibe Journal visualization */}
          <AnimatedCard className="lg:col-span-2" delay={300}>
            <div className="flex items-center gap-2 mb-6">
              <BarChart3 className="w-4 h-4 text-[hsl(var(--info))]" />
              <p className="text-xs uppercase tracking-widest text-muted-foreground">Recent Vibe Log</p>
            </div>
            <div className="flex items-center gap-1 h-32 overflow-hidden px-4">
              {(journal?.entries || []).map((entry: string, i: number) => {
                const colorMap: any = {
                    kids: "hsl(43 96% 56%)",
                    youths: "hsl(173 58% 39%)",
                    adults: "hsl(262 52% 62%)",
                    seniors: "hsl(346 72% 58%)"
                };
                return (
                  <div
                    key={i}
                    className="flex-1 min-w-[4px] rounded-full transition-all duration-300"
                    style={{
                        height: '100%',
                        backgroundColor: colorMap[entry] || 'hsl(var(--muted))',
                    }}
                    title={entry}
                  />
                );
              })}
              {(!journal || journal.entries.length === 0) && (
                <div className="w-full flex items-center justify-center text-muted-foreground text-xs uppercase tracking-widest opacity-20">
                    Waiting for detections...
                </div>
              )}
            </div>
          </AnimatedCard>

          {/* Age distribution */}
          <AnimatedCard delay={400}>
            <p className="text-xs uppercase tracking-widest text-muted-foreground mb-4">Demographic Split</p>
            <div className="space-y-4">
              {ageGroups.map((g, i) => {
                const pct = Math.round((g.count / totalFaces) * 100);
                return (
                    <div key={g.range} className="space-y-1.5">
                      <div className="flex justify-between items-center">
                        <span className="text-sm font-medium">{g.range}</span>
                        <span className="text-xs font-mono text-muted-foreground">{g.count} ({pct}%)</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-1000"
                          style={{ width: `${pct}%`, backgroundColor: g.color }}
                        />
                      </div>
                    </div>
                );
              })}
            </div>
          </AnimatedCard>
        </div>

        {/* Current state - real-time from WebSocket */}
        <AnimatedCard delay={500}>
            <div className="flex items-center gap-2 mb-4">
                <UserCheck className="w-4 h-4 text-[hsl(var(--rose))]" />
                <p className="text-xs uppercase tracking-widest text-muted-foreground">Current Audience State</p>
            </div>
            {vibeState ? (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    <div className="p-3 rounded-lg bg-muted/30 border border-border/50 text-center">
                        <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">Detected Group</p>
                        <p className="text-lg font-bold text-[hsl(var(--info))]">{vibeState.detected_group.toUpperCase()}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-muted/30 border border-border/50 text-center">
                        <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">Estimated Age</p>
                        <p className="text-lg font-bold text-[hsl(var(--violet))]">{vibeState.age}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-muted/30 border border-border/50 text-center">
                        <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">Active Cameras</p>
                        <p className="text-lg font-bold text-[hsl(var(--success))]">{vibeState.active_cameras}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-muted/30 border border-border/50 text-center">
                        <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">Unique Faces</p>
                        <p className="text-lg font-bold text-[hsl(var(--rose))]">{vibeState.unique_faces}</p>
                    </div>
                </div>
            ) : (
                <div className="py-8 text-center text-muted-foreground text-xs uppercase tracking-widest opacity-20">
                    Waiting for detections...
                </div>
            )}
        </AnimatedCard>
      </div>
    </DashboardLayout>
  );
}
