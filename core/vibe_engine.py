import time
import logging
import statistics
import threading
from collections import deque, Counter

logger = logging.getLogger("VibeEngine")

class VibeEngine:
    """
    The Alchemy State Engine.
    Manages the 'Vibe Journal' (history of detections), calculates the dominant audience,
    and handles the '95% Handover' logic for smooth transitions.
    """
    def __init__(self, history_len=50, consensus_threshold=20):
        # Rolling window of detected groups: ['youths', 'adults', 'kids', ...]
        self.journal = deque(maxlen=history_len)
        self.lock = threading.Lock()

        # Debounce/Consensus logic
        self.consensus_threshold = consensus_threshold
        self.temp_consensus = deque(maxlen=consensus_threshold)
        self.last_consensus_vibe = "adults"

        # Current active state
        self.current_vibe = "adults" # Default
        self.next_vibe = None
        self.status = "VIBING"       # SEARCHING | LOADING | VIBING
        self.current_age = "..."

        # Age tracking for accurate average calculation
        self.recent_ages = deque(maxlen=30)  # Last 30 age detections
        self.average_age = 25  # Default

        # Mapping for averaging (kids=1, youths=2, adults=3, seniors=4)
        self.group_map = {"kids": 1, "youths": 2, "adults": 3, "seniors": 4}
        self.inv_map = {1: "kids", 2: "youths", 3: "adults", 4: "seniors"}

    def log_detection(self, group, age="..."):
        """
        Logs a new detected group into the journal with consensus debounce.
        Also tracks ages for accurate average calculation.
        """
        if group not in self.group_map:
            return

        with self.lock:
            # 1. Update temp consensus buffer
            self.temp_consensus.append(group)

            # 2. Track age if provided
            if age != "...":
                try:
                    age_num = int(age)
                    self.recent_ages.append(age_num)
                    # Calculate running average age
                    if len(self.recent_ages) > 0:
                        self.average_age = int(sum(self.recent_ages) / len(self.recent_ages))
                        self.current_age = str(self.average_age)
                except (ValueError, TypeError):
                    pass

            # 3. Check for consensus (100% agreement in small window)
            if len(self.temp_consensus) == self.consensus_threshold:
                counts = Counter(self.temp_consensus)
                most_common, count = counts.most_common(1)[0]

                if count >= self.consensus_threshold * 0.8: # 80% consensus
                    if most_common != self.last_consensus_vibe:
                        self.last_consensus_vibe = most_common
                        # Add to long-term journal ONLY when consensus changes or every N frames
                        self.journal.append(most_common)
                        logger.info(f"Vibe consensus: {most_common} (avg age: {self.average_age})")

    def get_dominant_vibe(self):
        """Calculates the dominant vibe based on the current journal."""
        with self.lock:
            if not self.journal:
                return self.current_vibe

            vals = [self.group_map[g] for g in self.journal]
            avg_val = round(statistics.mean(vals))
            dominant = self.inv_map.get(avg_val, "adults")

            return dominant

    def get_current_group(self):
        """
        Returns the current target group for music playback.
        Based on the most recently detected group or average age.
        """
        with self.lock:
            # If we have recent detections, use the dominant vibe
            if self.journal:
                return self.get_dominant_vibe()

            # Fallback to age-based grouping
            if self.average_age < 13:
                return "kids"
            elif self.average_age < 20:
                return "youths"
            elif self.average_age < 50:
                return "adults"
            else:
                return "seniors"

    def prepare_handover(self):
        """
        Called when music player hits 95% completion.
        Locks in the next vibe based on recent history.
        """
        next_vibe = self.get_dominant_vibe()
        self.next_vibe = next_vibe
        logger.info(f"Handover Prepared: Current[{self.current_vibe}] -> Next[{self.next_vibe}] (avg age: {self.average_age})")
        return next_vibe

    def commit_handover(self):
        """Called when track finishes. Updates current vibe."""
        if self.next_vibe:
            self.current_vibe = self.next_vibe
            self.next_vibe = None
        return self.current_vibe

    def get_state(self, player=None, camera_count=0, face_count=0) -> dict:
        """Returns the full state for the UI/WebSocket. Includes global system metrics."""
        dominant = self.get_dominant_vibe()

        with self.lock:
            # Get player status if provided
            p_status = player.get_status() if player else {}

            return {
                "status":         self.status,
                "detected_group": dominant,
                "current_vibe":   dominant,   # alias for UI
                "age":            str(self.current_age),
                "average_age":    self.average_age,
                "journal_count":  len(self.journal),
                "percent_pos":    float(p_status.get('percent', 0)),
                "is_playing":     bool(player.is_playing if player else False),
                "paused":         bool(p_status.get('paused', True)),
                "shuffle":        bool(p_status.get('shuffle', True)),
                "current_song":   str(p_status.get('song', "")),
                "next_vibe":      self.next_vibe,
                "active_cameras": int(camera_count),
                "unique_faces":   int(face_count)
            }

    def get_status(self):
        with self.lock:
            return {
                "current_vibe": self.current_vibe,
                "next_vibe": self.next_vibe,
                "journal_size": len(self.journal),
                "dominant_now": self.get_dominant_vibe(),
                "average_age": self.average_age
            }
