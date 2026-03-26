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
        self.volume = 70
        self.shuffle_mode = True
        
        # Playlist Management
        self.history = deque(maxlen=50) # Played songs
        self.queue = deque() # Upcoming songs (if shuffle off)
        self.current_group = "adults"
        
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
                    # Reading response on windows pipe is tricky without blocking
                    return None 
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.connect(self.socket_path)
                    s.sendall(msg.encode())
                    data = s.recv(4096).decode()
                    return json.loads(data.split('\n')[0])
        except Exception as e:
            # logger.error(f"IPC Error: {e}")
            return None

    def play(self, group=None):
        """Plays a song from the specified group (or current)."""
        if group:
            self.current_group = group
            
        folder = self.music_root / self.current_group
        songs = list(folder.glob("*.*"))
        valid_exts = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}
        songs = [s for s in songs if s.suffix.lower() in valid_exts]
        
        if not songs:
            logger.warning(f"No songs found in {self.current_group}")
            return

        if self.shuffle_mode:
            next_song = random.choice(songs)
        else:
            # Basic sequential logic (would need index tracking)
            next_song = songs[0] 

        self._load_file(str(next_song))

    def _load_file(self, filepath):
        self._send_ipc(["loadfile", filepath])
        self.current_song = Path(filepath).stem
        self.history.append(filepath)
        self.is_playing = True
        logger.info(f"Now Playing: {self.current_song}")

    def pause(self):
        self._send_ipc(["cycle", "pause"])
        self.is_playing = not self.is_playing

    def next_track(self):
        self.play() # Shuffle logic handles it

    def prev_track(self):
        if len(self.history) > 1:
            self.history.pop() # Remove current
            prev = self.history.pop() # Get previous
            self._load_file(prev)
        else:
            self.play()

    def set_volume(self, vol):
        self.volume = max(0, min(100, int(vol)))
        self._send_ipc(["set_property", "volume", self.volume])

    def toggle_shuffle(self):
        self.shuffle_mode = not self.shuffle_mode
        return self.shuffle_mode

    def get_status(self):
        # Query properties via IPC
        pos = self._send_ipc(["get_property", "percent-pos"])
        dur = self._send_ipc(["get_property", "duration"])
        
        return {
            "song": self.current_song or "None",
            "percent": pos.get("data") if pos and "data" in pos else 0,
            "duration": dur.get("data") if dur and "data" in dur else 0,
            "playing": self.is_playing,
            "paused": not self.is_playing,
            "shuffle": self.shuffle_mode,
            "group": self.current_group,
            "volume": self.volume
        }

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process = None
