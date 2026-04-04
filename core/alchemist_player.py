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
        return shutil.which('mpv') or "mpv"

    def _start_mpv(self):
        """Starts MPV in idle mode with IPC enabled."""
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
        """Background thread to poll MPV for position without blocking API calls."""
        def poller():
            while self.process is not None:
                try:
                    res = self._send_ipc_fast(["get_property", "percent-pos"])
                    if res and "data" in res and res["data"] is not None:
                        with self._lock:
                            self._cached_percent = float(res["data"])
                            self._last_pos_update = time.time()
                except Exception:
                    pass
                time.sleep(0.5)  # Poll every 500ms

        t = threading.Thread(target=poller, daemon=True, name="mpv-pos-poller")
        t.start()

    def _start_mpv_monitor(self):
        """Background thread to monitor MPV process and auto-restart if it crashes."""
        def monitor():
            while not self._shutdown_event.is_set():
                time.sleep(2)
                with self._lock:
                    proc = self.process

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

        try:
            msg = json.dumps({"command": command}) + "\n"

            if sys.platform == 'win32':
                with open(self.socket_path, 'r+b', buffering=0) as f:
                    f.write(msg.encode())
                    return None
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.05)  # 50ms timeout — much faster
                    s.connect(self.socket_path)
                    s.sendall(msg.encode())
                    data = s.recv(4096).decode()
                    return json.loads(data.split('\n')[0])
        except (socket.timeout, ConnectionRefusedError, BrokenPipeError):
            return None
        except Exception:
            return None

    def _send_ipc(self, command):
        """Standard IPC with moderate timeout (100ms for queries)."""
        if not self.process:
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
        except (socket.timeout, ConnectionRefusedError, BrokenPipeError):
            return None
        except Exception:
            return None

    def play(self, filepath: str):
        """Plays a specific file."""
        self._send_ipc(["loadfile", filepath])
        with self._lock:
            self.current_song = Path(filepath).stem
            self.song_history.append(filepath)
            self.is_playing = True
            self.paused = False
            self._cached_percent = 0.0
        logger.info(f"Now Playing: {self.current_song}")

    def next(self, group: str):
        """Plays a song from the specified group."""
        with self._lock:
            self.current_folder = group

        folder = self.music_root / group
        songs = list(folder.glob("*.*"))
        valid_exts = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"}
        songs = [s for s in songs if s.suffix.lower() in valid_exts]

        if not songs:
            logger.warning(f"No songs in {group}")
            return

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

        self.play(str(next_song))

    def continue_current_folder(self):
        """
        Play next song from the CURRENT folder.
        Used when a song finishes — keeps playing from same folder
        until the vibe engine signals a group change.
        """
        with self._lock:
            folder = self.current_folder
        self.next(folder)

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
        """Stops the MPV process."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
            self.process = None
        with self._lock:
            self.is_playing = False
            self._cached_percent = 0.0
