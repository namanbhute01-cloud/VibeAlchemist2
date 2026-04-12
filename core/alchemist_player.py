import os
import sys
import json
import time
import socket
import random
import logging
import subprocess
import shutil
import threading
from pathlib import Path
from collections import deque

logger = logging.getLogger("AlchemistPlayer")


class AlchemistPlayer:
    """
    Advanced MPV Wrapper for Vibe Alchemist V2.

    Improvements:
    - Cached position (no blocking IPC on every get_status call)
    - Background position polling for smooth progress updates
    - Faster IPC timeout (50ms for commands, 100ms for queries)
    - Thread-safe state management
    - Auto-restart MPV if it crashes
    """

    def __init__(self, music_root="OfflinePlayback"):
        self.music_root = Path(music_root).resolve()
        self.socket_path = self._get_socket_path()
        self.mpv_bin = self._find_mpv()

        # ── State (thread-safe) ──
        self._lock = threading.Lock()
        self.process = None
        self.current_song = None
        self.is_playing = False
        self.paused = False
        self.is_stopped = False  # NEW: Manual stop flag
        self.volume = 70
        self.shuffle_mode = True

        # ── Playlist ──
        self.song_history = deque(maxlen=50)
        self.current_folder = "adults"

        # ── Cached position (updated by background thread) ──
        self._cached_percent = 0.0
        self._last_pos_update = 0

        # ── Shutdown event (for clean thread termination) ──
        self._shutdown_event = threading.Event()

        # ── Start ──
        self._start_mpv()
        self._start_pos_poller()
        self._start_mpv_monitor()

    def _get_socket_path(self):
        if sys.platform == 'win32':
            return r'\\.\pipe\vibe_alchemist_mpv'
        return '/tmp/vibe_alchemist_mpv.sock'

    def _find_mpv(self):
        mpv_path = shutil.which('mpv')
        if mpv_path:
            logger.info(f"MPV found at: {mpv_path}")
        else:
            logger.critical("MPV NOT INSTALLED! Music playback disabled. "
                           "Install: apt-get install mpv (Linux) or brew install mpv (Mac)")
        return mpv_path

    def _start_mpv(self):
        """Starts MPV in idle mode with IPC enabled."""
        if not self.mpv_bin:
            logger.warning("MPV not installed — music playback disabled. Server will still run vision pipeline.")
            return
        if self.process:
            self.stop()

        if sys.platform != 'win32' and os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        cmd = [
            self.mpv_bin,
            "--idle",
            f"--input-ipc-server={self.socket_path}",
            "--no-video",
            f"--volume={self.volume}",
            "--force-window=no",       # No window = faster
            "--terminal=no",           # No terminal output
            "--msg-level=all=no",      # Suppress all messages
        ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)  # Reduced wait (was 1s)
            logger.info("MPV Engine Started")
        except Exception as e:
            logger.critical(f"Failed to start MPV: {e}")

    def _start_pos_poller(self):
        """
        Background thread to poll MPV for position without blocking API calls.
        Also detects song-end events: when percent-pos returns null or stays at 100,
        clears current_song so the handover loop can queue the next song.
        
        FIX: Track poller thread to prevent multiple pollers after restart.
        """
        # Stop existing poller if running
        if hasattr(self, '_poller_thread') and self._poller_thread is not None:
            logger.debug("Stopping existing poller before starting new one")
            # Old poller will exit when self._poller_running is set to False
            self._poller_running = False
            # Give it time to exit
            time.sleep(0.3)
        
        # Reset poller running flag
        self._poller_running = True
        high_count = 0  # Consecutive polls at >= 99%

        def poller():
            nonlocal high_count
            while self._poller_running and self.process is not None:
                try:
                    res = self._send_ipc_fast(["get_property", "percent-pos"])
                    if res and "data" in res and res["data"] is not None:
                        pos = float(res["data"])
                        with self._lock:
                            self._cached_percent = pos
                            self._last_pos_update = time.time()

                        # ── Song-end detection ──
                        # MPV in --idle mode: when a song finishes, percent-pos
                        # either returns null or stays at ~100. We detect consecutive
                        # high readings and auto-clear the current song.
                        if pos >= 99:
                            high_count += 1
                            if high_count >= 4:  # ~2 seconds at 99%+ = song ended
                                with self._lock:
                                    if self.is_playing and not self.paused:
                                        self.current_song = None
                                        self.is_playing = False
                                        self.paused = False
                                        self._cached_percent = 0.0
                                        logger.info("Song ended (position poller)")
                                high_count = 0
                        else:
                            high_count = 0
                    else:
                        # null response from IPC — could be:
                        # 1. MPV has no active file (idle mode) → song ended
                        # 2. IPC call failed (socket missing during restart) → ignore
                        # Only treat as song-end if we actually got a response (not None)
                        if res is not None and "data" in res:
                            # Actual null data = no active file
                            with self._lock:
                                if self.is_playing:
                                    self.current_song = None
                                    self.is_playing = False
                                    self.paused = False
                                    self._cached_percent = 0.0
                                    logger.info("Song ended (null position = idle)")
                            high_count = 0
                        else:
                            # IPC returned None (socket missing, etc.) — ignore
                            pass
                except Exception:
                    pass
                time.sleep(0.5)  # Poll every 500ms

        t = threading.Thread(target=poller, daemon=True, name="mpv-pos-poller")
        t.start()
        self._poller_thread = t

    def _start_mpv_monitor(self):
        """Background thread to monitor MPV process and auto-restart if it crashes."""
        def monitor():
            while not self._shutdown_event.is_set():
                time.sleep(2)
                with self._lock:
                    proc = self.process
                    stopped = self.is_stopped

                # FIX: Don't restart if user manually stopped
                if stopped:
                    continue

                if proc is not None:
                    poll_result = proc.poll()
                    if poll_result is not None:
                        logger.warning(f"MPV process died (exit code: {poll_result}), restarting...")
                        with self._lock:
                            self.process = None
                            self.is_playing = False
                        self._start_mpv()
                        self._start_pos_poller()

        t = threading.Thread(target=monitor, daemon=True, name="mpv-monitor")
        t.start()

    def _send_ipc_fast(self, command):
        """Fast IPC with short timeout (50ms for commands)."""
        if not self.process:
            return None

        # Check if MPV process is still alive BEFORE trying to connect
        if self.process.poll() is not None:
            # MPV died — let the monitor thread restart it, don't restart here (prevents race condition)
            return None

        # MPV is alive — if socket doesn't exist, don't restart here either (let monitor handle it)
        if not os.path.exists(self.socket_path):
            return None

        try:
            msg = json.dumps({"command": command}) + "\n"

            if sys.platform == 'win32':
                with open(self.socket_path, 'r+b', buffering=0) as f:
                    f.write(msg.encode())
                    return None
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.05)  # 50ms timeout
                    s.connect(self.socket_path)
                    s.sendall(msg.encode())
                    data = s.recv(4096).decode()
                    return json.loads(data.split('\n')[0])
        except (socket.timeout, ConnectionRefusedError, BrokenPipeError, FileNotFoundError):
            return None
        except Exception:
            return None

    def _send_ipc(self, command):
        """Standard IPC with moderate timeout (100ms for queries)."""
        if not self.process:
            return None

        # Check if MPV process is still alive BEFORE trying to connect
        if self.process.poll() is not None:
            return None

        # MPV is alive — if socket doesn't exist, don't restart here
        if not os.path.exists(self.socket_path):
            return None

        try:
            msg = json.dumps({"command": command}) + "\n"

            if sys.platform == 'win32':
                with open(self.socket_path, 'r+b', buffering=0) as f:
                    f.write(msg.encode())
                    return None
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.1)  # 100ms
                    s.connect(self.socket_path)
                    s.sendall(msg.encode())
                    data = s.recv(4096).decode()
                    return json.loads(data.split('\n')[0])
        except (socket.timeout, ConnectionRefusedError, BrokenPipeError, FileNotFoundError):
            return None
        except Exception:
            return None

    def play(self, filepath: str = None):
        """
        Plays a specific file, or the next track from the loaded playlist.
        Returns True if playback started successfully.
        """
        if not self.process or not os.path.exists(self.socket_path):
            logger.warning(f"MPV not ready — cannot play {filepath}")
            return False

        # If no filepath given, pick next from playlist
        if filepath is None:
            if not hasattr(self, "_playlist") or not self._playlist:
                logger.warning("No playlist loaded")
                return False

            if self.shuffle_mode:
                filepath = str(random.choice(self._playlist))
            else:
                filepath = str(self._playlist[self._playlist_index % len(self._playlist)])
                self._playlist_index = (self._playlist_index + 1) % len(self._playlist)

        result = self._send_ipc(["loadfile", filepath])
        if result is None:
            logger.warning(f"IPC failed for {filepath} — MPV may be restarting")
            return False

        # Apply LUFS-based volume adjustment
        self._apply_lufs_gain(filepath)

        with self._lock:
            self.current_song = Path(filepath).stem
            self.song_history.append(filepath)
            self.is_playing = True
            self.paused = False
            self._cached_percent = 0.0
            self.is_stopped = False  # Clear stopped flag when starting new song
        logger.info(f"Now Playing: {self.current_song}")
        return True

    def _apply_lufs_gain(self, track_path: str):
        """
        Read LUFS sidecar and adjust pygame/mpv volume accordingly.
        Sidecar format: {track_path}.lufs → {"lufs": -23.5, "gain_db": +9.5, "target": -14.0}
        """
        sidecar = track_path + ".lufs"
        if not os.path.exists(sidecar):
            return  # no sidecar — play at default volume

        try:
            with open(sidecar) as f:
                data = json.load(f)
            gain_db = float(data.get("gain_db", 0.0))
            # Convert dB gain to linear multiplier
            linear = 10 ** (gain_db / 20.0)
            # Apply to current volume setting
            adjusted_volume = max(0, min(100, self.volume * linear))
            self._send_ipc_fast(["set_property", "volume", round(adjusted_volume, 1)])
            logger.debug(
                f"LUFS gain: {gain_db:+.1f} dB → volume {self.volume} → {adjusted_volume:.1f}"
            )
        except Exception as e:
            logger.debug(f"LUFS sidecar read failed for {os.path.basename(track_path)}: {e}")
            # Keep current volume — no harm done

    def next(self, group: str):
        """Plays a song from the specified group. Returns True if playback started."""
        with self._lock:
            self.current_folder = group
            self.is_stopped = False  # Clear stopped flag when starting new song

        folder = self.music_root / group
        songs = list(folder.glob("*.*"))
        valid_exts = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"}
        songs = [s for s in songs if s.suffix.lower() in valid_exts]

        if not songs:
            logger.warning(f"No songs in {group}")
            return False

        # Pick a song NOT in recent history (avoid repeats)
        recent_files = set(str(s) for s in list(self.song_history)[-5:])
        available = [s for s in songs if str(s) not in recent_files]
        if not available:
            available = songs  # Fallback: all songs

        if self.shuffle_mode:
            next_song = random.choice(available)
        else:
            # Sequential: pick next song not in history
            next_song = available[0]

        return self.play(str(next_song))

    def continue_current_folder(self):
        """
        Play next song from the CURRENT folder.
        Used when a song finishes — keeps playing from same folder
        until the vibe engine signals a group change.
        Returns True if playback started.
        """
        with self._lock:
            folder = self.current_folder
        return self.next(folder)

    def prev(self):
        """Plays the previous song from history."""
        with self._lock:
            if len(self.song_history) > 1:
                self.song_history.pop()  # Remove current
                prev_file = self.song_history.pop()  # Get previous
                self.play(prev_file)
            else:
                self.next(self.current_folder)

    def toggle_pause(self):
        """Toggles play/pause state — instant local state change + async IPC."""
        with self._lock:
            self.paused = not self.paused
        # Send IPC asynchronously (don't wait for response)
        self._send_ipc_fast(["cycle", "pause"])

    def toggle_shuffle(self) -> bool:
        """Toggles shuffle mode."""
        with self._lock:
            self.shuffle_mode = not self.shuffle_mode
            return self.shuffle_mode

    def set_volume(self, level: int):
        """Sets output volume."""
        with self._lock:
            self.volume = max(0, min(100, int(level)))
        self._send_ipc_fast(["set_property", "volume", self.volume])

    def get_pos(self) -> float:
        """Returns cached position percentage (no blocking IPC)."""
        with self._lock:
            # Stale check: if no update in 3s, return 0
            if time.time() - self._last_pos_update > 3:
                return 0.0
            return self._cached_percent

    def is_active(self) -> bool:
        """Returns True if engine is running."""
        return self.is_playing and self.process is not None

    def get_status(self) -> dict:
        """Returns full status — NO blocking IPC calls."""
        with self._lock:
            return {
                "song":    self.current_song or "None",
                "percent": float(self._cached_percent),
                "paused":  bool(self.paused),
                "shuffle": bool(self.shuffle_mode),
                "group":   str(self.current_folder),
                "volume":  int(self.volume),
            }

    def stop(self):
        """Stops the MPV process and sets stopped flag."""
        if self.process:
            try:
                self._send_ipc_fast(["stop"])
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        with self._lock:
            self.is_playing = False
            self.is_stopped = True  # Mark as manually stopped
            self.current_song = None
            self._cached_percent = 0.0

    def load_playlist(self, folder_path: str, shuffle: bool = True) -> bool:
        """
        Load all audio files from a folder into the player's context.
        Does NOT start playback — call play() separately.
        :param folder_path: Path to folder containing music files.
        :param shuffle: Whether to enable shuffle mode for this playlist.
        :returns: True if files were found, False if folder is empty/invalid.
        """
        from pathlib import Path

        folder = Path(folder_path)
        if not folder.is_dir():
            logger.warning(f"Playlist folder not found: {folder_path}")
            return False

        valid_exts = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"}
        songs = [s for s in folder.iterdir() if s.suffix.lower() in valid_exts]

        if not songs:
            logger.warning(f"No audio files in: {folder_path}")
            return False

        self.shuffle_mode = shuffle
        self._playlist = songs
        self._playlist_index = 0
        logger.info(f"Loaded {len(songs)} tracks from {folder_path}")
        return True
