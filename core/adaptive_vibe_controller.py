"""
Adaptive VibeController — wraps FuzzyVibeEngine + tier awareness.
On Tier 1 (no demographics): only uses recognized name or default.
On Tier 2/3: uses fuzzy inference with age + energy.
"""
import os
import logging
from core.capability_detector import PROFILE

logger = logging.getLogger(__name__)


class AdaptiveVibeController:
    def __init__(self, audio_engine):
        self._audio = audio_engine
        self._root = os.getenv("ROOT_MUSIC_DIR", "./OfflinePlayback")
        self._shuffle = os.getenv("SHUFFLE_MODE", "true").lower() == "true"
        self._current_folder = None
        self._fuzzy = None

        if PROFILE.tier >= 2:
            try:
                from core.fuzzy_vibe_engine import FuzzyVibeEngine
                self._fuzzy = FuzzyVibeEngine()
                logger.info("AdaptiveVibeController: fuzzy logic ENABLED")
            except Exception as e:
                logger.warning(f"FuzzyVibeEngine failed: {e} — using fallback")
        else:
            logger.info("AdaptiveVibeController: fuzzy DISABLED (Tier 1), name-only mode")

    def update(self, name: str, age: float, energy: float, crowd: int):
        # Known person always gets priority
        if name != "unknown" and name:
            folder_path = os.path.join(self._root, name)
            if os.path.isdir(folder_path):
                self._switch(folder_path)
                return

        # Tier 2/3: use fuzzy logic for unknowns
        if self._fuzzy:
            folder_name = self._fuzzy.get_vibe_folder(age, energy, crowd)
            self._switch(os.path.join(self._root, folder_name))
        else:
            # Tier 1: just play default
            self._switch(os.path.join(self._root, "default"))

    def _switch(self, full_path: str):
        if full_path == self._current_folder:
            return
        if not os.path.isdir(full_path):
            default = os.path.join(self._root, "default")
            if os.path.isdir(default):
                full_path = default
            else:
                return
        self._current_folder = full_path
        logger.info(f"VibeController: switched to {full_path}")

    def stop(self):
        self._current_folder = None
        try:
            self._audio.stop()
        except Exception:
            pass
