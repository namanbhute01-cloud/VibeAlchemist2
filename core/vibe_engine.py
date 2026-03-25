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
    def __init__(self, history_len=50):
        # Rolling window of detected groups: ['youths', 'adults', 'kids', ...]
        self.journal = deque(maxlen=history_len)
        self.lock = threading.Lock()
        
        # Current active state
        self.current_vibe = "adults" # Default
        self.next_vibe = None
        
        # Mapping for averaging (kids=1, youths=2, adults=3, seniors=4)
        self.group_map = {"kids": 1, "youths": 2, "adults": 3, "seniors": 4}
        self.inv_map = {1: "kids", 2: "youths", 3: "adults", 4: "seniors"}

    def log_detection(self, group):
        """Logs a new detected group into the journal."""
        if group not in self.group_map:
            return

        with self.lock:
            self.journal.append(group)
            
    def get_dominant_vibe(self):
        """Calculates the dominant vibe based on the current journal."""
        with self.lock:
            if not self.journal:
                return self.current_vibe
            
            # Simple Mode (Most Frequent)
            # counts = Counter(self.journal)
            # most_common = counts.most_common(1)[0][0]
            
            # Weighted Average approach (matches legacy alcha.py logic)
            # This allows a mix of kids+adults to drift towards 'youths' music potentially
            vals = [self.group_map[g] for g in self.journal]
            avg_val = round(statistics.mean(vals))
            dominant = self.inv_map.get(avg_val, "adults")
            
            return dominant

    def prepare_handover(self):
        """
        Called when music player hits 95% completion.
        Locks in the next vibe based on recent history.
        """
        next_vibe = self.get_dominant_vibe()
        self.next_vibe = next_vibe
        logger.info(f"Handover Prepared: Current[{self.current_vibe}] -> Next[{self.next_vibe}]")
        return next_vibe

    def commit_handover(self):
        """Called when track finishes. Updates current vibe."""
        if self.next_vibe:
            self.current_vibe = self.next_vibe
            self.next_vibe = None
        return self.current_vibe

    def get_status(self):
        with self.lock:
            return {
                "current_vibe": self.current_vibe,
                "next_vibe": self.next_vibe,
                "journal_size": len(self.journal),
                "dominant_now": self.get_dominant_vibe()
            }
