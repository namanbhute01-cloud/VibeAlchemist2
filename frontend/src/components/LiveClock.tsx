import { useEffect, useState } from "react";

export function LiveClock() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const hours = time.getHours().toString().padStart(2, "0");
  const minutes = time.getMinutes().toString().padStart(2, "0");
  const seconds = time.getSeconds().toString().padStart(2, "0");

  return (
    <div className="flex items-center gap-1 font-mono text-sm tabular-nums text-muted-foreground">
      <span className="text-foreground font-semibold">{hours}</span>
      <span className="animate-pulse text-primary">:</span>
      <span className="text-foreground font-semibold">{minutes}</span>
      <span className="animate-pulse text-primary">:</span>
      <span>{seconds}</span>
    </div>
  );
}
