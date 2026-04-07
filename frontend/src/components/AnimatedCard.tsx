import { cn } from "@/lib/utils";
import { useState } from "react";

interface AnimatedCardProps {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}

export function AnimatedCard({ children, className, delay = 0 }: AnimatedCardProps) {
  const [mounted] = useState(true);

  return (
    <div
      className={cn(
        "rounded-xl border border-border/50 bg-card p-5 transition-all duration-300",
        "hover:shadow-lg hover:shadow-primary/5 hover:-translate-y-0.5",
        "active:translate-y-0 active:scale-[0.995] active:shadow-md",
        "animate-float-in",
        className
      )}
      style={{ animationDelay: mounted ? `${delay}ms` : '0ms', animationFillMode: "forwards", animationIterationCount: "1" }}
    >
      {children}
    </div>
  );
}
