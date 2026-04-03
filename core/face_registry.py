"""
Face Registry V2 - Improved Cross-Camera Face Identity Management

Manages known face identities using ArcFace embeddings.
Improvements over V1:
- Higher similarity threshold (0.55) for more reliable matching
- Age-aware matching (considers age proximity in matching)
- Face tracking with detection count per identity
- Better pruning with configurable staleness
- Thread-safe operations with fine-grained locking
"""

import numpy as np
import time
import logging
import threading
from collections import deque
from numpy.linalg import norm

logger = logging.getLogger("FaceRegistry")


class FaceRegistry:
    def __init__(self, threshold=0.55, prune_interval=3600):
        """
        Args:
            threshold: Cosine similarity threshold for face matching (0.55 = balanced)
            prune_interval: Seconds before stale faces are removed (default: 1 hour)
        """
        self.threshold = threshold
        self.prune_interval = prune_interval

        # face_id -> {embedding, group, age, last_seen, cam_ids, first_seen, detection_count, age_history}
        self.known_faces = {}
        self.saved_faces = set()

        self.last_prune = time.time()
        self.lock = threading.Lock()
        self.face_counter = 0

        # Age tracking for matching
        self.age_tolerance = 10  # Allow ±10 years in age-based matching

        logger.info(f"FaceRegistry V2 initialized (threshold={threshold}, prune={prune_interval}s)")

    def _cosine_similarity(self, emb1, emb2):
        """Cosine similarity between two embeddings."""
        if emb1 is None or emb2 is None:
            return 0.0
        try:
            return float(np.dot(emb1, emb2) / (norm(emb1) * norm(emb2)))
        except Exception:
            return 0.0

    def is_known(self, embedding, age=None):
        """
        Check if embedding matches any known face.
        Uses both embedding similarity AND age proximity for matching.

        Returns: (face_id, similarity, age) or (None, 0.0, None)
        """
        with self.lock:
            best_sim = 0.0
            best_id = None
            best_age = None

            for fid, data in self.known_faces.items():
                sim = self._cosine_similarity(embedding, data['embedding'])

                # Age-aware matching: boost score if ages are close
                if age is not None and data.get('age') is not None:
                    age_diff = abs(age - data['age'])
                    if age_diff <= self.age_tolerance:
                        # Small age boost for close ages (max +0.05)
                        age_boost = 0.05 * (1 - age_diff / self.age_tolerance)
                        sim += age_boost

                if sim > best_sim:
                    best_sim = sim
                    best_id = fid
                    best_age = data.get('age')

            if best_sim > self.threshold:
                return best_id, best_sim, best_age

            return None, 0.0, None

    def register(self, embedding, group, cam_id, age=None):
        """
        Register a new face identity.
        Returns face ID in format: {group}_{age}_{unique_id}
        """
        with self.lock:
            self.face_counter += 1
            age_str = str(age) if age is not None else "unknown"
            new_id = f"{group}_{age_str}_{self.face_counter}"

            self.known_faces[new_id] = {
                'embedding': embedding.copy(),  # Copy to prevent mutation
                'group': group,
                'age': age,
                'last_seen': time.time(),
                'cam_ids': {cam_id},
                'first_seen': time.time(),
                'detection_count': 1,
                'age_history': deque([age], maxlen=10) if age is not None else deque(maxlen=10),
                'saved': False
            }

            logger.info(
                f"New Identity: {new_id} | "
                f"Group: {group} | Age: {age} | Cam: {cam_id}"
            )
            return new_id

    def update(self, face_id, cam_id=None):
        """Update face identity with new detection."""
        with self.lock:
            if face_id not in self.known_faces:
                return

            data = self.known_faces[face_id]
            data['last_seen'] = time.time()
            data['detection_count'] += 1

            if cam_id is not None:
                data['cam_ids'].add(cam_id)

            # Periodic pruning
            if time.time() - self.last_prune > 300:
                self._prune()

    def update_age(self, face_id, new_age):
        """Update the age estimate for a known face with temporal smoothing."""
        with self.lock:
            if face_id not in self.known_faces:
                return

            data = self.known_faces[face_id]
            if new_age is not None:
                data['age_history'].append(new_age)

                # Update stored age with running average
                if len(data['age_history']) > 0:
                    data['age'] = int(np.mean(list(data['age_history'])))

    def get_age_estimate(self, face_id):
        """Get the best age estimate for a face identity."""
        with self.lock:
            if face_id in self.known_faces:
                data = self.known_faces[face_id]
                if len(data['age_history']) > 0:
                    return int(np.mean(list(data['age_history'])))
                return data.get('age')
            return None

    def get_cameras_for_face(self, face_id):
        """Get all cameras where this face has been detected."""
        with self.lock:
            if face_id in self.known_faces:
                return self.known_faces[face_id]['cam_ids'].copy()
            return set()

    def get_detection_count(self, face_id):
        """Get how many times a face has been detected."""
        with self.lock:
            if face_id in self.known_faces:
                return self.known_faces[face_id]['detection_count']
            return 0

    def get_summary(self) -> dict:
        """Return summary of unique people by group."""
        by_group = {"kids": 0, "youths": 0, "adults": 0, "seniors": 0}
        with self.lock:
            for data in self.known_faces.values():
                g = data.get('group', 'adults')
                if g in by_group:
                    by_group[g] += 1
            return {
                "total_unique": len(self.known_faces),
                "by_group": by_group
            }

    def get_saved_count(self) -> int:
        """Count of faces saved to vault."""
        with self.lock:
            return len(self.saved_faces)

    def mark_as_saved(self, face_id):
        """Mark face as saved to vault."""
        with self.lock:
            if face_id in self.known_faces:
                self.known_faces[face_id]['saved'] = True
                self.saved_faces.add(face_id)

    def is_saved(self, face_id):
        """Check if face has been saved."""
        with self.lock:
            return face_id in self.saved_faces

    def get_known_faces_info(self) -> list:
        """Get info about all known faces (for debugging/API)."""
        with self.lock:
            result = []
            for fid, data in self.known_faces.items():
                result.append({
                    'id': fid,
                    'group': data.get('group'),
                    'age': data.get('age'),
                    'cameras': list(data.get('cam_ids', set())),
                    'detections': data.get('detection_count', 0),
                    'last_seen': data.get('last_seen', 0),
                    'saved': data.get('saved', False)
                })
            return sorted(result, key=lambda x: x['last_seen'], reverse=True)

    def _prune(self):
        """Remove faces not seen for longer than prune_interval."""
        now = time.time()
        to_remove = []

        for fid, data in self.known_faces.items():
            if now - data['last_seen'] > self.prune_interval:
                to_remove.append(fid)

        for fid in to_remove:
            del self.known_faces[fid]
            self.saved_faces.discard(fid)

        if to_remove:
            logger.info(f"Pruned {len(to_remove)} stale face identities")

        self.last_prune = now

    def clear(self):
        """Clear all registered faces."""
        with self.lock:
            self.known_faces.clear()
            self.saved_faces.clear()
            self.face_counter = 0
            logger.info("Face registry cleared")
