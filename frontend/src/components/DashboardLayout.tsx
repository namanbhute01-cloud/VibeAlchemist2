import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { DriveStatus } from "./DriveStatus";
import { useVibeStream } from "@/hooks/useVibeStream";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const vibeState = useVibeStream();
  
  // Use vibeState directly (it's flat now)
  const isTransitioning = vibeState && vibeState.next_vibe !== null;


  return (
    <SidebarProvider>
      <div className="min-h-screen flex w-full">
        <AppSidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <header className="h-14 flex items-center border-b border-border/40 px-5 shrink-0 backdrop-blur-sm bg-background/80 sticky top-0 z-10">
            <SidebarTrigger className="text-muted-foreground hover:text-foreground transition-colors" />
            <div className="ml-auto flex items-center gap-4">
              {/* Vibe Status Pill */}
              <Badge 
                variant="secondary" 
                className={cn(
                  "gap-1.5 px-2 py-0.5 text-[10px] uppercase font-bold tracking-wider transition-colors",
                  isTransitioning ? "bg-amber-500/10 text-amber-500 border-amber-500/20" : "bg-green-500/10 text-green-500 border-green-500/20"
                )}
              >
                <span className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  isTransitioning ? "bg-amber-500 animate-pulse" : "bg-green-500"
                )} />
                {isTransitioning ? "Transitioning" : "Vibing"}
              </Badge>

              {/* Drive Status Badge */}
              <DriveStatus />

              <div className="flex items-center gap-2 text-xs text-muted-foreground ml-2">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                </span>
                System Online
              </div>
            </div>
          </header>
          <main className="flex-1 overflow-auto p-6 scrollbar-thin pb-24">
            {children}
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}
