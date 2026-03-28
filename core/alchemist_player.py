import os
import sys
import json
import time
import socket
import random
import logging
import subprocess
import shutil
from pathlib import Path
from collections import deque

logger = logging.getLogger("AlchemistPlayer")

class AlchemistPlayer:
    """
    Advanced MPV Wrapper for Vibe Alchemist.
    Features: Shuffle, History (Prev/Next), Volume, JSON IPC.
    """
    def __init__(self, music_root="OfflinePlayback"):
        self.music_root = Path(music_root).resolve()
        self.socket_path = self._get_socket_path()
        self.mpv_bin = self._find_mpv()
        
        # State
        self.process = None
        self.current_song = None
        self.is_playing = False
        self.paused = False
        self.volume = 70
        self.shuffle_mode = True
        
        # Playlist Management
        self.song_history = deque(maxlen=50) # Played songs
        self.current_folder = "adults"
        
        # Start MPV idle
        self._start_mpv()

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

        # Remove old socket file if exists (Linux/Mac)
        if sys.platform != 'win32' and os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        cmd = [
            self.mpv_bin,
            "--idle",
            f"--input-ipc-server={self.socket_path}",
            "--no-video",
            f"--volume={self.volume}"
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            time.sleep(1) # Wait for socket
            logger.info("MPV Engine Started.")
        except Exception as e:
            logger.critical(f"Failed to start MPV: {e}")

    def _send_ipc(self, command):
        """Sends a JSON command to MPV socket."""
        if not self.process: return None
        
        try:
            msg = json.dumps({"command": command}) + "\n"
            
            if sys.platform == 'win32':
                with open(self.socket_path, 'r+b', buffering=0) as f:
                    f.write(msg.encode())
                    return None 
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.2)
                    s.connect(self.socket_path)
                    s.sendall(msg.encode())
                    data = s.recv(4096).decode()
                    return json.loads(data.split('\n')[0])
        except Exception:
            return None

    def play(self, filepath: str):
        """Plays a specific file."""
        self._send_ipc(["loadfile", filepath])
        self.current_song = Path(filepath).stem
        self.song_history.append(filepath)
        self.is_playing = True
        self.paused = False
        logger.info(f"Now Playing: {self.current_song}")

    def next(self, group: str):
        """Plays a song from the specified group."""
        self.current_folder = group
        folder = self.music_root / group
        songs = list(folder.glob("*.*"))
        valid_exts = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"}
        songs = [s for s in songs if s.suffix.lower() in valid_exts]
        
        if not songs:
            logger.warning(f"No songs found in {group}")
            return

        if self.shuffle_mode:
            next_song = random.choice(songs)
        else:
            next_song = songs[0] 

        self.play(str(next_song))

    def prev(self):
        """Plays the previous song from history."""
        if len(self.song_history) > 1:
            self.song_history.pop() # Remove current
            prev_file = self.song_history.pop() # Get previous
            self.play(prev_file)
        else:
            self.next(self.current_folder)

    def toggle_pause(self):
        """Toggles play/pause state."""
        self._send_ipc(["cycle", "pause"])
        self.paused = not self.paused
        # Note: self.is_playing should strictly mean 'engine active'
        # but for the UI we might use it as 'actually making sound'
        # Following spec: is_playing should be engine active.

    def toggle_shuffle(self) -> bool:
        """Toggles shuffle mode."""
        self.shuffle_mode = not self.shuffle_mode
        return self.shuffle_mode

    def set_volume(self, level: int):
        """Sets output volume."""
        self.volume = max(0, min(100, int(level)))
        self._send_ipc(["set_property", "volume", self.volume])

    def get_pos(self) -> float:
        """Returns current playback percentage."""
        res = self._send_ipc(["get_property", "percent-pos"])
        if res and "data" in res and res["data"] is not None:
            return float(res["data"])
        return 0.0

    def is_active(self) -> bool:
        """Returns True if a file is loaded and engine is running."""
        return self.is_playing and self.process is not None

    def get_status(self) -> dict:
        """Returns full status for API."""
        return {
            "song":    self.current_song or "None",
            "percent": float(self.get_pos()),
            "paused":  bool(self.paused),
            "shuffle": bool(self.shuffle_mode),
            "group":   str(self.current_folder),
            "volume":  int(self.volume),
        }

    def stop(self):
        """Stops the MPV process."""
        if self.process:
            self.process.terminate()
            self.process = None
        self.is_playing = False
