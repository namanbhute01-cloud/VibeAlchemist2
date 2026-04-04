"""
Vibe Engine V2 - Improved Audience State Management

Manages the 'Vibe Journal' (history of detections), calculates the dominant audience,
and handles the '95% Handover' logic for smooth transitions.

Improvements over V1:
- Quality-weighted detection logging (good-quality detections count more)
- Per-camera detection tracking (know which cameras are active)
- Better consensus algorithm with quality weighting
- Age tracking with per-identity smoothing
- Stale detection cleanup
"""

import time
import logging
import statistics
import threading
from collections import deque, Counter

logger = logging.getLogger("VibeEngine")


class VibeEngine:
    def __init__(self, history_len=50, consensus_threshold=20):
        # Rolling window of detected groups: ['youths', 'adults', 'kids', ...]
        self.journal = deque(maxlen=history_len)
        self.lock = threading.Lock()

        # Debounce/Consensus logic
        self.consensus_threshold = consensus_threshold
        self.temp_consensus = deque(maxlen=consensus_threshold)
        self.last_consensus_vibe = "adults"

        # Current active state
        self.current_vibe = "adults"
        self.next_vibe = None
        self.current_age = "..."

        # Age tracking
        self.recent_ages = deque(maxlen=30)
        self.average_age = 25

        # ── NEW: Quality-weighted detection tracking ──
        # Track detections per camera to know which sources are active
        self.camera_detections = {}  # cam_id -> last_detection_time
        self.active_cameras = set()

        # Quality-weighted journal entries: (group, quality, timestamp)
        self.quality_journal = deque(maxlen=history_len)

        # Group mapping
        self.group_map = {"kids": 1, "youths": 2, "adults": 3, "seniors": 4}
        self.inv_map = {1: "kids", 2: "youths", 3: "adults", 4: "seniors"}

        # Stale detection cleanup
        self.last_cleanup = time.time()
        self.stale_threshold = 30  # Seconds before a camera is considered inactive

        logger.info("VibeEngine V2 initialized with quality-weighted detection")

    def log_detection(self, group, age="...", quality=1.0, cam_id=None):
        """
        Log a new detection with quality weighting.

        Args:
            group: Age group (kids/youths/adults/seniors)
            age: Numeric age or "..."
            quality: Detection quality (0.0-1.0). Higher = more reliable.
            cam_id: Camera ID that detected this face.
        """
        if group not in self.group_map:
            return

        with self.lock:
            # Track camera activity
            if cam_id is not None:
                self.camera_detections[cam_id] = time.time()
                self.active_cameras.add(cam_id)

            # Track age
            if age != "...":
                try:
                    age_num = int(age)
                    self.recent_ages.append(age_num)
                    if len(self.recent_ages) > 0:
                        self.average_age = int(sum(self.recent_ages) / len(self.recent_ages))
                        self.current_age = str(self.average_age)
                except (ValueError, TypeError):
                    pass

            # Quality-weighted consensus: good detections count more
            # Add detection to consensus buffer weighted by quality
            quality_weight = max(0.1, min(1.0, quality))

            # Add to quality journal for detailed tracking (single source of truth)
            self.quality_journal.append({
                'group': group,
                'quality': quality_weight,
                'timestamp': time.time(),
                'cam_id': cam_id
            })

            # Add to temp consensus — one entry per quality_journal entry, kept in sync
            self.temp_consensus.append(group)
            if quality_weight > 0.7:
                # High quality detections get extra weight in consensus
                self.temp_consensus.append(group)

            # Check for consensus — use temp_consensus length as trigger,
            # but vote from the matching slice of quality_journal
            if len(self.temp_consensus) >= self.consensus_threshold:
                # Quality-weighted voting from recent quality_journal entries
                # Take the most recent entries matching temp_consensus size
                recent_entries = list(self.quality_journal)[-len(self.temp_consensus):]
                quality_votes = {}
                for entry in recent_entries:
                    g = entry['group']
                    q = entry['quality']
                    quality_votes[g] = quality_votes.get(g, 0) + q

                if quality_votes:
                    most_common = max(quality_votes, key=quality_votes.get)
                    total_quality = sum(quality_votes.values())
                    dominant_quality = quality_votes.get(most_common, 0)

                    # Only change vibe if dominant group has significant quality weight
                    if dominant_quality / total_quality > 0.6 and most_common != self.last_consensus_vibe:
                        self.last_consensus_vibe = most_common
                        self.journal.append(most_common)
                        logger.info(
                            f"Vibe consensus: {most_common} | "
                            f"Quality: {dominant_quality/total_quality:.2f} | "
                            f"Avg age: {self.average_age} | "
                            f"Active cameras: {len(self.active_cameras)}"
                        )

                # Reset temp consensus
                self.temp_consensus.clear()

            # Periodic cleanup of stale cameras
            if time.time() - self.last_cleanup > 60:
                self._cleanup_stale()

    def _cleanup_stale(self):
        """Remove cameras that haven't detected anything recently."""
        now = time.time()
        stale_cameras = []

        for cam_id, last_time in self.camera_detections.items():
            if now - last_time > self.stale_threshold:
                stale_cameras.append(cam_id)

        for cam_id in stale_cameras:
            self.active_cameras.discard(cam_id)
            del self.camera_detections[cam_id]
            logger.debug(f"Camera {cam_id} marked as inactive (no detections for {self.stale_threshold}s)")

        self.last_cleanup = now

    def get_active_camera_count(self):
        """Get number of cameras with recent detections."""
        with self.lock:
            self._cleanup_stale()
            return len(self.active_cameras)

    def get_dominant_vibe(self):
        """Calculate dominant vibe from the journal."""
        with self.lock:
            if not self.journal:
                return self.current_vibe

            vals = [self.group_map[g] for g in self.journal]
            avg_val = round(statistics.mean(vals))
            return self.inv_map.get(avg_val, "adults")

    def get_current_group(self):
        """
        Get current target group for music playback.
        Uses quality-weighted recent detections.
        """
        with self.lock:
            # Check quality journal for recent high-quality detections
            if self.quality_journal:
                now = time.time()
                recent = [
                    entry for entry in self.quality_journal
                    if now - entry['timestamp'] < 30  # Last 30 seconds
                ]

                if recent:
                    # Quality-weighted vote
                    quality_votes = {}
                    for entry in recent:
                        g = entry['group']
                        q = entry['quality']
                        quality_votes[g] = quality_votes.get(g, 0) + q

                    if quality_votes:
                        return max(quality_votes, key=quality_votes.get)

            # Fallback to journal-based vibe
            if self.journal:
                return self.get_dominant_vibe()

            # Final fallback to age-based
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
        Called when music player hits ~95% completion.
        Locks in the next vibe based on recent quality-weighted detections.
        Returns the target group for the next song.
        """
        with self.lock:
            # Determine next vibe from recent quality-weighted detections
            next_vibe = self.get_current_group()

            # Only prepare handover if vibe is different from current
            if next_vibe != self.current_vibe:
                self.next_vibe = next_vibe
                logger.info(
                    f"Handover Prepared (95%): {self.current_vibe} -> {self.next_vibe} | "
                    f"Avg age: {self.average_age} | "
                    f"Active cameras: {len(self.active_cameras)}"
                )
            else:
                # Same vibe — no transition needed, just continue
                self.next_vibe = None
                logger.info(
                    f"Handover Skipped: Still {self.current_vibe} | "
                    f"Avg age: {self.average_age}"
                )

            return next_vibe

    def commit_handover(self):
        """
        Called when track finishes.
        If a handover was prepared, updates current vibe.
        Returns the target group for the next song.
        """
        with self.lock:
            if self.next_vibe and self.next_vibe != self.current_vibe:
                old_vibe = self.current_vibe
                self.current_vibe = self.next_vibe
                logger.info(
                    f"Handover Committed: {old_vibe} -> {self.current_vibe}"
                )
                target = self.current_vibe
            else:
                # No vibe change — continue with current folder
                target = self.current_vibe
                logger.info(f"Handover: Continuing {target}")

            self.next_vibe = None
            return target

    def get_state(self, player=None, camera_count=0, face_count=0) -> dict:
        """Return full state for UI/WebSocket."""
        dominant = self.get_dominant_vibe()

        with self.lock:
            p_status = player.get_status() if player else {}
            active_cams = len(self.active_cameras)

            return {
                "status": "active" if player and player.is_playing else "idle",
                "detected_group": dominant,
                "current_vibe": dominant,
                "age": str(self.current_age),
                "average_age": self.average_age,
                "journal_count": len(self.journal),
                "percent_pos": float(p_status.get('percent', 0)),
                "is_playing": bool(player.is_playing if player else False),
                "paused": bool(p_status.get('paused', True)),
                "shuffle": bool(p_status.get('shuffle', True)),
                "current_song": str(p_status.get('song', "")),
                "next_vibe": self.next_vibe,
                "active_cameras": max(active_cams, camera_count),
                "unique_faces": int(face_count)
            }

    def get_status(self):
        """Return concise status."""
        with self.lock:
            return {
                "current_vibe": self.current_vibe,
                "next_vibe": self.next_vibe,
                "journal_size": len(self.journal),
                "dominant_now": self.get_dominant_vibe(),
                "average_age": self.average_age,
                "active_cameras": len(self.active_cameras)
            }
