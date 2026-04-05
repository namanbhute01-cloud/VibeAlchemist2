import { cn } from "@/lib/utils";
import { AnimatedCard } from "./AnimatedCard";
import { LucideIcon, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useEffect, useState, useRef, memo } from "react";

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: string | number;
  sub?: string;
  delay?: number;
  glow?: boolean;
  trend?: "up" | "down" | "neutral";
  color?: "amber" | "teal" | "rose" | "violet";
}

const colorMap = {
  amber: {
    icon: "text-primary",
    iconBg: "bg-primary/10 group-hover:bg-primary/20",
    glow: "glow-amber border-primary/20",
    hoverGlow: "group-hover:bg-primary/5",
    ring: "group-hover:ring-primary/20",
  },
  teal: {
    icon: "text-[hsl(var(--info))]",
    iconBg: "bg-[hsl(var(--info)/0.1)] group-hover:bg-[hsl(var(--info)/0.2)]",
    glow: "glow-teal border-[hsl(var(--info)/0.2)]",
    hoverGlow: "group-hover:bg-[hsl(var(--info)/0.05)]",
    ring: "group-hover:ring-[hsl(var(--info)/0.2)]",
  },
  rose: {
    icon: "text-[hsl(var(--rose))]",
    iconBg: "bg-[hsl(var(--rose)/0.1)] group-hover:bg-[hsl(var(--rose)/0.2)]",
    glow: "glow-rose border-[hsl(var(--rose)/0.2)]",
    hoverGlow: "group-hover:bg-[hsl(var(--rose)/0.05)]",
    ring: "group-hover:ring-[hsl(var(--rose)/0.2)]",
  },
  violet: {
    icon: "text-[hsl(var(--violet))]",
    iconBg: "bg-[hsl(var(--violet)/0.1)] group-hover:bg-[hsl(var(--violet)/0.2)]",
    glow: "glow-violet border-[hsl(var(--violet)/0.2)]",
    hoverGlow: "group-hover:bg-[hsl(var(--violet)/0.05)]",
    ring: "group-hover:ring-[hsl(var(--violet)/0.2)]",
  },
};

function useAnimatedCounter(target: number, duration = 600) {
  const [count, setCount] = useState(target);
  const prevTarget = useRef(target);
  const currentCount = useRef(target);
  const ref = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (prevTarget.current !== target) {
      const from = currentCount.current;
      const delta = target - from;
      prevTarget.current = target;
      const start = performance.now();
      const animate = (now: number) => {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        const val = Math.round(from + delta * eased);
        currentCount.current = val;
        setCount(val);
        if (progress < 1) requestAnimationFrame(animate);
        else { currentCount.current = target; setCount(target); }
      };
      requestAnimationFrame(animate);
    }
  }, [target, duration]);

  return { count, ref };
}

export const StatCard = memo(function StatCard({ icon: Icon, label, value, sub, delay = 0, glow, trend, color = "amber" }: StatCardProps) {
  const TrendIcon = trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;
  const trendColor = trend === "up" ? "text-[hsl(var(--success))]" : trend === "down" ? "text-[hsl(var(--rose))]" : "text-muted-foreground";
  const c = colorMap[color];

  const isNumeric = typeof value === "number";
  const { count, ref: counterRef } = useAnimatedCounter(isNumeric ? value : 0);

  return (
    <AnimatedCard delay={delay} className={cn(
      "group relative overflow-hidden cursor-pointer",
      "ring-1 ring-transparent transition-all duration-300",
      c.ring,
      glow && c.glow
    )}>
      <div className={cn("absolute -top-8 -right-8 w-24 h-24 rounded-full bg-transparent transition-all duration-500 blur-2xl", c.hoverGlow)} />
      
      <div className="relative flex items-start justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2.5 flex items-center gap-2">
            {label}
            {trend && (
              <span className={cn("inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9px] font-medium", 
                trend === "up" && "bg-[hsl(var(--success)/0.1)]",
                trend === "down" && "bg-[hsl(var(--rose)/0.1)]",
                trend === "neutral" && "bg-muted",
                trendColor
              )}>
                <TrendIcon className="w-2.5 h-2.5" />
              </span>
            )}
          </p>
          <p ref={counterRef} className="text-4xl font-bold tracking-tighter tabular-nums">
            {isNumeric ? count : value}
          </p>
          {sub && <p className="text-xs text-muted-foreground mt-1.5">{sub}</p>}
        </div>
        <div className={cn(
          "w-11 h-11 rounded-xl flex items-center justify-center transition-all duration-300",
          "group-hover:scale-110 group-hover:rotate-3",
          "group-active:scale-95",
          c.iconBg
        )}>
          <Icon className={cn("w-5 h-5 transition-transform duration-300", c.icon)} />
        </div>
      </div>

      {/* Bottom shimmer line on hover */}
      <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-transparent to-transparent group-hover:via-current opacity-0 group-hover:opacity-20 transition-opacity duration-500" style={{ color: `hsl(var(--${color === 'amber' ? 'primary' : color === 'teal' ? 'info' : color}))` }} />
    </AnimatedCard>
  );
});
