import { AnimatedCard } from "./AnimatedCard";
import { Users } from "lucide-react";

interface AgeGaugeProps {
  avgAge: string | number;
  ageBreakdown: { range: string; count: number; color: string }[];
  delay?: number;
}

export function AgeGauge({ avgAge, ageBreakdown, delay = 0 }: AgeGaugeProps) {
  const total = ageBreakdown.reduce((s, b) => s + b.count, 0);
  const ageNum = typeof avgAge === 'string' ? parseFloat(avgAge) || 0 : avgAge;

  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const ageNormalized = Math.min(ageNum / 60, 1);
  const offset = circumference * (1 - ageNormalized);

  return (
    <AnimatedCard delay={delay} className="group">
      <div className="flex items-center gap-2 mb-4">
        <Users className="w-4 h-4 text-[hsl(var(--info))]" />
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Age Distribution</p>
      </div>

      <div className="flex items-center gap-6 mb-2">
        <div className="relative w-24 h-24 shrink-0">
          <svg className="w-24 h-24 -rotate-90" viewBox="0 0 96 96">
            <circle cx="48" cy="48" r={radius} fill="none" stroke="hsl(var(--muted))" strokeWidth="6" />
            <circle
              cx="48" cy="48" r={radius} fill="none"
              stroke="hsl(var(--info))"
              strokeWidth="6" strokeLinecap="round"
              strokeDasharray={circumference} strokeDashoffset={offset}
              className="transition-all duration-1000 ease-out"
              style={{ filter: "drop-shadow(0 0 4px hsl(173 58% 39% / 0.4))" }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-bold tabular-nums text-[hsl(var(--info))] leading-none">{avgAge}</span>
            <span className="text-[8px] uppercase tracking-[0.2em] text-muted-foreground mt-0.5">Avg Age</span>
          </div>
        </div>

        <div className="flex-1 space-y-2.5">
          {ageBreakdown.map((group, i) => (
            <div key={group.range} className="flex items-center gap-2">
              <span className="text-[11px] text-muted-foreground w-12 shrink-0 font-mono">{group.range}</span>
              <div className="flex-1 h-2.5 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${total ? (group.count / total) * 100 : 0}%`,
                    backgroundColor: group.color,
                    animation: `float-in 0.6s cubic-bezier(0.16, 1, 0.3, 1) ${(delay || 0) + i * 100}ms forwards`,
                    boxShadow: `0 0 8px ${group.color}40`,
                  }}
                />
              </div>
              <span className="text-[11px] tabular-nums text-muted-foreground w-6 text-right font-mono">{group.count}</span>
            </div>
          ))}
        </div>
      </div>
    </AnimatedCard>
  );
}
