import { cn } from "@/lib/utils";
import { useEffect, useRef, useState } from "react";

interface AnimatedCardProps {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}

export function AnimatedCard({ children, className, delay = 0 }: AnimatedCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [animKey, setAnimKey] = useState(0);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setVisible(true); },
      { threshold: 0.15 }
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  // Re-trigger animation when children change
  useEffect(() => {
    setVisible(false);
    setAnimKey(k => k + 1);
    const timer = setTimeout(() => setVisible(true), 50);
    return () => clearTimeout(timer);
  }, [children]);

  return (
    <div
      key={animKey}
      ref={ref}
      className={cn(
        "rounded-xl border border-border/50 bg-card p-5 transition-all duration-300",
        "hover:shadow-lg hover:shadow-primary/5 hover:-translate-y-0.5",
        "active:translate-y-0 active:scale-[0.995] active:shadow-md",
        visible ? "animate-float-in" : "opacity-0",
        className
      )}
      style={{ animationDelay: `${delay}ms`, animationFillMode: "forwards" }}
    >
      {children}
    </div>
  );
}
