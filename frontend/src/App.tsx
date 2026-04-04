import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider } from "next-themes";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { MusicPlayer } from "@/components/MusicPlayer";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import Index from "./pages/Index.tsx";
import NotFound from "./pages/NotFound.tsx";
import Cameras from "./pages/Cameras.tsx";
import Audience from "./pages/Audience.tsx";
import Playlist from "./pages/Playlist.tsx";
import Analytics from "./pages/Analytics.tsx";
import Settings from "./pages/Settings.tsx";

const queryClient = new QueryClient();

// Keyboard shortcuts wrapper component
function KeyboardShortcuts() {
  useKeyboardShortcuts();
  return null;
}

const App = () => (
  <ErrorBoundary>
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <Toaster />
          <Sonner />
          <BrowserRouter>
            <KeyboardShortcuts />
            <Routes>
              <Route path="/" element={<Index />} />
              <Route path="/cameras" element={<Cameras />} />
              <Route path="/audience" element={<Audience />} />
              <Route path="/playlist" element={<Playlist />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
            <MusicPlayer />
          </BrowserRouter>
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </ErrorBoundary>
);

export default App;
