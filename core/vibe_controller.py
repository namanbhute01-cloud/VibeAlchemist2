"""
VibeController: Integrates fuzzy logic, demographics, and emotion
to select and switch music folders automatically.

Called from the main pipeline every 30th frame.
Decides music folder and switches playback if the vibe has changed.

Logic:
    - If a known person is recognized (confidence > threshold): use their personal folder
    - Otherwise: use FuzzyVibeEngine output (age + energy + crowd → folder)
"""
import os
import logging

from core.fuzzy_vibe_engine import FuzzyVibeEngine

logger = logging.getLogger(__name__)


class VibeController:
    def __init__(self, audio_engine):
        """
        :param audio_engine: AlchemistPlayer instance (handles playback).
        """
        self._audio = audio_engine
        self._fuzzy = FuzzyVibeEngine()
        self._current_person = None
        self._current_folder = None
        self._music_root = os.getenv("ROOT_MUSIC_DIR", "./OfflinePlayback")
        self._shuffle = os.getenv("SHUFFLE_MODE", "true").lower() == "true"
        self._known_priority = (
            os.getenv("KNOWN_PERSON_PRIORITY", "true").lower() == "true"
        )
        self._confidence_threshold = float(os.getenv("FUZZY_CONFIDENCE_MIN", 0.65))

        logger.info(
            f"VibeController initialized "
            f"(root={self._music_root}, shuffle={self._shuffle}, "
            f"known_priority={self._known_priority})"
        )

    def update(
        self,
        person_name: str,
        age: float,
        energy: float,
        crowd_size: int,
        confidence: float = 0.0,
    ):
        """
        Called from main pipeline every 30th frame.
        Determines music folder and switches if changed.

        :param person_name: Recognized person name, or "unknown".
        :param age: Estimated age in years.
        :param energy: Emotional energy (0-1).
        :param crowd_size: Number of tracked persons.
        :param confidence: Recognition confidence (0-1).
        """
        # ── Determine target folder ──
        if self._known_priority and person_name not in (None, "unknown"):
            # Recognized person: use their personal folder
            folder = os.path.join(self._music_root, person_name)
            if not os.path.isdir(folder):
                logger.debug(
                    f"Personal folder not found for '{person_name}', "
                    f"falling back to fuzzy vibe"
                )
                folder = self._fuzzy.get_vibe_folder(age, energy, crowd_size)
        else:
            # Unknown person: use fuzzy logic
            folder = self._fuzzy.get_vibe_folder(age, energy, crowd_size)

        # Resolve to absolute path
        full_folder = folder if os.path.isabs(folder) else os.path.abspath(folder)

        # ── Check if vibe changed ──
        if full_folder == self._current_folder:
            return  # already playing correct music

        # ── Switch music ──
        prev_folder = self._current_folder or "none"
        logger.info(
            f"Vibe change: '{prev_folder}' -> "
            f"'{full_folder}' (person={person_name}, age={age:.0f}, "
            f"energy={energy:.2f}, crowd={crowd_size})"
        )

        self._current_folder = full_folder
        self._current_person = person_name

        # Load and play new playlist
        try:
            success = self._audio.load_playlist(full_folder, shuffle=self._shuffle)
            if success:
                self._audio.play()
                logger.info(f"Now playing from: {full_folder}")
            else:
                logger.warning(f"No music found in: {full_folder}")
        except Exception as e:
            logger.error(f"Failed to load playlist {full_folder}: {e}")

    def stop(self):
        """Stop playback and reset state."""
        self._current_person = None
        self._current_folder = None
        try:
            self._audio.stop()
        except Exception as e:
            logger.error(f"VibeController stop error: {e}")

    def get_current_state(self) -> dict:
        """Returns current vibe state for API /status endpoint."""
        return {
            "current_person": self._current_person or "unknown",
            "current_folder": self._current_folder or "none",
            "music_root": self._music_root,
            "shuffle": self._shuffle,
            "known_priority": self._known_priority,
        }
