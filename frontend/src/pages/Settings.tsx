import { DashboardLayout } from "@/components/DashboardLayout";
import { AnimatedCard } from "@/components/AnimatedCard";
import { Settings as SettingsIcon, Camera, Music, Wifi, Shield, Save, RotateCcw, Eye, Check, X } from "lucide-react";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { useVibeStream } from "@/hooks/useVibeStream";
import { api } from "@/lib/api";

type EnvVar = { key: string; value: string; masked: boolean; category: string };

const categories = [
  { id: "cameras", label: "Camera Config", icon: Camera, color: "info" },
  { id: "detection", label: "Detection AI", icon: Shield, color: "rose" },
  { id: "music", label: "Music API", icon: Music, color: "violet" },
  { id: "system", label: "System", icon: Wifi, color: "primary" },
];

// Toggle settings config — keys match UPPERCASE env var names in backend schema
type ToggleConfig = { label: string; description: string; key: string; default: boolean };

const toggleSettings: ToggleConfig[] = [
  { label: "Auto-adjust playlist", description: "Automatically change songs based on real-time age detection", key: "AUTO_PLAYLIST", default: true },
  { label: "Face detection overlay", description: "Show bounding boxes on camera feeds", key: "FACE_OVERLAY", default: true },
  { label: "Shuffle mode", description: "Play songs in random order within age group", key: "SHUFFLE_MODE", default: true },
  { label: "Privacy mode", description: "Blur faces in the dashboard feed display", key: "PRIVACY_MODE", default: false },
];

function Toggle({ enabled, onChange }: { enabled: boolean; onChange: () => void }) {
  return (
    <button
      onClick={onChange}
      className={`relative w-11 h-6 rounded-full transition-colors duration-200 ${enabled ? "bg-primary" : "bg-muted"}`}
      role="switch"
      aria-checked={enabled}
    >
      <div
        className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-foreground transition-transform duration-200 ${enabled ? "translate-x-5 bg-primary-foreground" : ""}`}
      />
    </button>
  );
}

export default function SettingsPage() {
  const vibeState = useVibeStream();
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [activeCategory, setActiveCategory] = useState("cameras");
  const [toggles, setToggles] = useState<Record<string, boolean>>(
    Object.fromEntries(toggleSettings.map(s => [s.key, s.default]))
  );
  const [revealedKeys, setRevealedKeys] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [cameraSources, setCameraSources] = useState<string>("");
  const [savingCameras, setSavingCameras] = useState(false);
  const [savingToggles, setSavingToggles] = useState<Record<string, boolean>>({});
  const [savingEdit, setSavingEdit] = useState(false);

  // Load all config from backend on mount
  useEffect(() => {
    const loadData = async () => {
      try {
        // Load camera config
        const camConfig = await api.getCameraConfig();
        if (camConfig.sources) {
          setCameraSources(camConfig.sources.join(", "));
        }

        // Load env vars from backend (replaces mock data)
        const envVarsResp = await api.getEnvVars();
        if (envVarsResp.ok && envVarsResp.env_vars) {
          setEnvVars(envVarsResp.env_vars);
        }

        // Load toggle settings from backend
        const settingsResp = await api.getSettings();
        if (settingsResp.ok && settingsResp.settings) {
          const backendSettings = settingsResp.settings;
          // Map uppercase keys from backend to toggle state
          setToggles(prev => {
            const updated = { ...prev };
            toggleSettings.forEach(toggle => {
              if (backendSettings[toggle.key] !== undefined) {
                updated[toggle.key] = Boolean(backendSettings[toggle.key]);
              }
            });
            return updated;
          });
        }
      } catch (error) {
        console.error("Failed to load config:", error);
        toast.error("Failed to load configuration");
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, []);

  const filteredVars = envVars.filter(v => v.category === activeCategory);

  const startEdit = (env: EnvVar) => {
    setEditingKey(env.key);
    setEditValue(env.value);
  };

  const saveEdit = async () => {
    if (!editingKey) return;
    setSavingEdit(true);

    try {
      const result = await api.updateEnvVar(editingKey, editValue);

      if (result.ok) {
        // Update local state with confirmed value from backend
        setEnvVars(prev => prev.map(v => v.key === editingKey ? { ...v, value: editValue } : v));
        setEditingKey(null);
        toast.success(`${editingKey} updated and saved to .env`);

        // If we edited camera sources, update the camera sources field too
        if (editingKey === "CAMERA_SOURCES") {
          setCameraSources(editValue);
        }
      } else {
        toast.error("Failed to save", { description: result.error });
      }
    } catch (error) {
      console.error("Save edit error:", error);
      toast.error("Failed to save setting");
    } finally {
      setSavingEdit(false);
    }
  };

  const cancelEdit = () => {
    setEditingKey(null);
    setEditValue("");
  };

  const toggleReveal = (key: string) => {
    setRevealedKeys(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const handleSaveCameras = async () => {
    setSavingCameras(true);
    try {
      const sources = cameraSources.split(",").map(s => s.trim()).filter(s => s !== "");

      if (sources.length === 0) {
        toast.error("At least one camera source is required");
        return;
      }

      const result = await api.saveCameraConfig(sources);

      if (result.ok) {
        toast.success("Camera sources saved", {
          description: `Updated to ${sources.length} source(s). Restart required for some changes.`
        });
        // Also update the CAMERA_SOURCES env var display
        setEnvVars(prev => prev.map(v =>
          v.key === "CAMERA_SOURCES" ? { ...v, value: cameraSources } : v
        ));
      } else {
        toast.error("Failed to save", { description: result.error });
      }
    } catch (error) {
      console.error("Error saving camera config:", error);
      toast.error("Failed to save camera sources");
    } finally {
      setSavingCameras(false);
    }
  };

  const handleReset = async () => {
    try {
      // Reset toggles to defaults in backend
      const defaults: Record<string, boolean> = {};
      toggleSettings.forEach(s => { defaults[s.key] = s.default; });
      await api.saveSettings(defaults);

      // Update local state
      setToggles(Object.fromEntries(toggleSettings.map(s => [s.key, s.default])));
      toast.success("Settings reset to defaults and saved to .env");

      // Reload env vars to reflect changes
      const envVarsResp = await api.getEnvVars();
      if (envVarsResp.ok && envVarsResp.env_vars) {
        setEnvVars(envVarsResp.env_vars);
      }
    } catch (error) {
      console.error("Reset error:", error);
      toast.error("Failed to reset settings");
    }
  };

  const handleToggleChange = async (key: string, newValue: boolean) => {
    // Optimistic update
    setToggles(prev => ({ ...prev, [key]: newValue }));
    setSavingToggles(prev => ({ ...prev, [key]: true }));

    try {
      // Send with UPPERCASE key to match backend schema
      const result = await api.saveSettings({ [key]: newValue });
      if (result.ok) {
        toast.success(`${toggleSettings.find(s => s.key === key)?.label || key} updated and saved to .env`);

        // Reload env vars to reflect the change in the env vars list too
        const envVarsResp = await api.getEnvVars();
        if (envVarsResp.ok && envVarsResp.env_vars) {
          setEnvVars(envVarsResp.env_vars);
        }
      } else {
        // Revert on error
        setToggles(prev => ({ ...prev, [key]: !newValue }));
        toast.error("Failed to save setting", { description: result.error });
      }
    } catch (error) {
      console.error("Toggle save error:", error);
      setToggles(prev => ({ ...prev, [key]: !newValue }));
      toast.error("Failed to save setting");
    } finally {
      setSavingToggles(prev => ({ ...prev, [key]: false }));
    }
  };

  return (
    <DashboardLayout>
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-end justify-between gap-4 pb-2 border-b border-border/30" style={{ animation: "float-in 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards" }}>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <SettingsIcon className="w-5 h-5 text-primary" />
              <span className="text-xs font-medium text-primary uppercase tracking-widest">Configuration</span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
            <p className="text-sm text-muted-foreground mt-1">Environment variables, preferences & system config</p>
          </div>
          <div className="flex gap-2">
            <button onClick={handleReset} className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-border/50 text-xs text-muted-foreground hover:bg-muted/50 transition-colors">
              <RotateCcw className="w-3.5 h-3.5" /> Reset
            </button>
            <button onClick={handleSaveCameras} disabled={savingCameras} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-primary text-primary-foreground text-xs hover:bg-primary/90 transition-colors disabled:opacity-50">
              <Save className="w-3.5 h-3.5" /> {savingCameras ? "Saving..." : "Save All"}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Env Variables */}
          <div className="lg:col-span-2 space-y-4">
            <div className="flex items-center gap-3" style={{ animation: "float-in 0.5s ease-out 100ms forwards", opacity: 0 }}>
              <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-widest">Environment Variables</h2>
              <div className="flex-1 h-px bg-border/30" />
            </div>

            {/* Category tabs */}
            <div className="flex gap-2 flex-wrap" style={{ animation: "float-in 0.5s ease-out 150ms forwards", opacity: 0 }}>
              {categories.map(cat => (
                <button
                  key={cat.id}
                  onClick={() => setActiveCategory(cat.id)}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                    activeCategory === cat.id
                      ? `bg-[hsl(var(--${cat.color}))/0.12] text-[hsl(var(--${cat.color}))] border border-[hsl(var(--${cat.color}))/0.3]`
                      : "text-muted-foreground border border-border/50 hover:bg-muted/30"
                  }`}
                >
                  <cat.icon className="w-3.5 h-3.5" />
                  {cat.label}
                </button>
              ))}
            </div>

            {/* Camera Sources Editor (shown in cameras tab) */}
            {activeCategory === "cameras" && (
              <AnimatedCard delay={180}>
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Camera className="w-4 h-4 text-[hsl(var(--info))]" />
                    <h3 className="text-sm font-medium">Camera Sources</h3>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Enter camera sources separated by commas. Use <code className="bg-muted px-1 rounded">0</code> for default webcam, or URLs for IP cameras.
                  </p>
                  <textarea
                    value={cameraSources}
                    onChange={(e) => setCameraSources(e.target.value)}
                    placeholder="0, http://192.168.1.100:8080/video, rtsp://camera-ip/stream"
                    className="w-full h-24 text-sm bg-card border border-border/50 rounded-lg px-3 py-2 font-mono focus:outline-none focus:border-[hsl(var(--info))/0.5] transition-colors resize-none"
                  />
                  <div className="flex gap-2 text-xs">
                    <button
                      onClick={() => setCameraSources("0")}
                      className="px-2 py-1 rounded bg-muted/50 hover:bg-muted transition-colors"
                    >
                      Default Webcam
                    </button>
                    <button
                      onClick={() => setCameraSources("0, http://192.168.29.173:8080/video")}
                      className="px-2 py-1 rounded bg-muted/50 hover:bg-muted transition-colors"
                    >
                      + IP Camera
                    </button>
                  </div>
                </div>
              </AnimatedCard>
            )}

            {/* Var list */}
            <AnimatedCard delay={200}>
              {loading ? (
                <div className="py-8 text-center text-muted-foreground">Loading configuration...</div>
              ) : (
                <div className="space-y-1">
                  {filteredVars.map((env, i) => {
                    const isEditing = editingKey === env.key;
                    const isRevealed = revealedKeys.has(env.key);
                    const displayValue = env.masked && !isRevealed ? "•".repeat(16) : env.value;

                    return (
                      <div
                        key={env.key}
                        className={`flex items-center gap-3 px-3 py-3 rounded-lg transition-all duration-200 ${isEditing ? "bg-primary/5 border border-primary/20" : "hover:bg-muted/30 border border-transparent"}`}
                        style={{ animation: `float-in 0.4s ease-out ${200 + i * 60}ms forwards`, opacity: 0 }}
                      >
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-mono font-medium text-[hsl(var(--info))]">{env.key}</p>
                          {isEditing ? (
                            <div className="flex gap-2 mt-1.5">
                              <input
                                value={editValue}
                                onChange={(e) => setEditValue(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") saveEdit();
                                  if (e.key === "Escape") cancelEdit();
                                }}
                                className="flex-1 text-sm bg-card border border-border/50 rounded px-2 py-1 font-mono focus:outline-none focus:border-primary/50"
                                autoFocus
                                disabled={savingEdit}
                              />
                              <button onClick={saveEdit} disabled={savingEdit} className="p-1 rounded hover:bg-[hsl(var(--success))]/20 text-[hsl(var(--success))] transition-colors disabled:opacity-50"><Check className="w-4 h-4" /></button>
                              <button onClick={cancelEdit} className="p-1 rounded hover:bg-destructive/20 text-destructive transition-colors"><X className="w-4 h-4" /></button>
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground font-mono truncate mt-0.5">{displayValue}</p>
                          )}
                        </div>
                        {!isEditing && (
                          <div className="flex items-center gap-1.5 shrink-0">
                            {env.masked && (
                              <button onClick={() => toggleReveal(env.key)} className="p-1 rounded hover:bg-muted/50 transition-colors text-muted-foreground">
                                <Eye className="w-3.5 h-3.5" />
                              </button>
                            )}
                            <button onClick={() => startEdit(env)} className="text-[10px] text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded hover:bg-muted/50">
                              Edit
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </AnimatedCard>
          </div>

          {/* Preferences */}
          <div className="space-y-4">
            <div className="flex items-center gap-3" style={{ animation: "float-in 0.5s ease-out 200ms forwards", opacity: 0 }}>
              <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-widest">Preferences</h2>
              <div className="flex-1 h-px bg-border/30" />
            </div>

            <AnimatedCard delay={300}>
              <div className="space-y-1">
                {toggleSettings.map((setting, i) => (
                  <div
                    key={setting.key}
                    className="flex items-center gap-3 px-3 py-3 rounded-lg hover:bg-muted/30 transition-colors"
                    style={{ animation: `float-in 0.4s ease-out ${300 + i * 60}ms forwards`, opacity: 0 }}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{setting.label}</p>
                      <p className="text-[11px] text-muted-foreground">{setting.description}</p>
                    </div>
                    <div className="flex items-center gap-1">
                      {savingToggles[setting.key] && (
                        <span className="text-[10px] text-muted-foreground">Saving...</span>
                      )}
                      <Toggle
                        enabled={toggles[setting.key]}
                        onChange={() => handleToggleChange(setting.key, !toggles[setting.key])}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </AnimatedCard>

            {/* System info */}
            <AnimatedCard delay={450}>
              <div className="flex items-center gap-2 mb-3">
                <Shield className="w-4 h-4 text-[hsl(var(--success))]" />
                <p className="text-xs uppercase tracking-widest text-muted-foreground">System Status</p>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between items-center py-1.5">
                  <span className="text-muted-foreground">Backend Status</span>
                  <span className="flex items-center gap-1.5 font-mono text-xs">
                    <span className="w-1.5 h-1.5 rounded-full bg-[hsl(var(--success))]" />
                    {vibeState?.status || "Connected"}
                  </span>
                </div>
                <div className="flex justify-between items-center py-1.5">
                  <span className="text-muted-foreground">Current Vibe</span>
                  <span className="font-mono text-xs">{vibeState?.current_vibe || "Unknown"}</span>
                </div>
                <div className="flex justify-between items-center py-1.5">
                  <span className="text-muted-foreground">Detected Group</span>
                  <span className="font-mono text-xs capitalize">{vibeState?.detected_group || "None"}</span>
                </div>
                <div className="flex justify-between items-center py-1.5">
                  <span className="text-muted-foreground">Music Engine</span>
                  <span className="font-mono text-xs">{vibeState?.is_playing ? "Playing" : "Idle"}</span>
                </div>
              </div>
            </AnimatedCard>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
