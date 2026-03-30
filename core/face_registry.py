import numpy as np
import time
import logging
import threading
from numpy.linalg import norm

logger = logging.getLogger("FaceRegistry")

class FaceRegistry:
    """
    Manages known face identities using ArcFace embeddings.
    Prevents duplicate detection of the same person across frames and cameras.
    Also tracks which faces have been saved to avoid duplicate saves.
    """
    def __init__(self, threshold=0.55, prune_interval=3600):
        self.threshold = threshold  # Lowered from 0.65 to 0.55 for better matching
        self.prune_interval = prune_interval
        # id -> {'embedding': np.array, 'group': str, 'last_seen': float, 'cam_id': int}
        self.known_faces = {}
        # Track which faces have been saved to vault (to avoid duplicates)
        self.saved_faces = set()
        self.last_prune = time.time()
        self.lock = threading.Lock()

    def _cosine_similarity(self, emb1, emb2):
        """Calculates cosine similarity between two vectors."""
        if emb1 is None or emb2 is None:
            return 0.0
        return np.dot(emb1, emb2) / (norm(emb1) * norm(emb2))

    def is_known(self, embedding):
        """
        Checks if the embedding matches any known face.
        Returns: (face_id, similarity) if found, else (None, 0.0)
        """
        with self.lock:
            best_sim = 0.0
            best_id = None

            for fid, data in self.known_faces.items():
                sim = self._cosine_similarity(embedding, data['embedding'])
                if sim > best_sim:
                    best_sim = sim
                    best_id = fid

            if best_sim > self.threshold:
                return best_id, best_sim

            return None, 0.0

    def register(self, embedding, group, cam_id):
        """
        Registers a new face.
        Returns the new face ID.
        """
        with self.lock:
            # Simple ID generation
            new_id = f"face_{len(self.known_faces) + 1}_{int(time.time())}"

            self.known_faces[new_id] = {
                'embedding': embedding,
                'group': group,
                'last_seen': time.time(),
                'cam_id': cam_id,
                'first_seen': time.time(),
                'saved': False  # Track if this face has been saved
            }
            logger.info(f"New Identity Registered: {new_id} (Group: {group}, Cam: {cam_id})")
            return new_id

    def mark_as_saved(self, face_id):
        """Mark a face as saved to vault to prevent duplicate saves."""
        with self.lock:
            if face_id in self.known_faces:
                self.known_faces[face_id]['saved'] = True
                self.saved_faces.add(face_id)
                logger.debug(f"Marked {face_id} as saved")

    def is_saved(self, face_id):
        """Check if a face has already been saved."""
        with self.lock:
            return face_id in self.saved_faces

    def update(self, face_id, cam_id=None):
        """Updates the last_seen timestamp for a known face."""
        with self.lock:
            if face_id in self.known_faces:
                self.known_faces[face_id]['last_seen'] = time.time()
                if cam_id is not None:
                    self.known_faces[face_id]['cam_id'] = cam_id

                # Prune old faces periodically
                if time.time() - self.last_prune > 300:
                    self._prune()

    def get_summary(self) -> dict:
        """Returns counts of people detected by group."""
        by_group = {"kids": 0, "youths": 0, "adults": 0, "seniors": 0}
        with self.lock:
            for rec in self.known_faces.values():
                # Handle both dict and object (if any)
                g = rec.get('group', 'adults') if isinstance(rec, dict) else getattr(rec, 'group', 'adults')
                if g in by_group:
                    by_group[g] += 1
            return {"total_unique": len(self.known_faces), "by_group": by_group}

    def get_saved_count(self) -> int:
        """Returns the count of faces saved to vault."""
        with self.lock:
            return len(self.saved_faces)

    def _prune(self):
        """Removes faces not seen for a long time."""
        now = time.time()
        to_remove = []
        for fid, data in self.known_faces.items():
            if now - data['last_seen'] > self.prune_interval:
                to_remove.append(fid)

        for fid in to_remove:
            del self.known_faces[fid]
            self.saved_faces.discard(fid)
            logger.debug(f"Pruned stale identity: {fid}")

        self.last_prune = now

    def clear(self):
        """Clear all registered faces (used on shutdown)."""
        with self.lock:
            self.known_faces.clear()
            self.saved_faces.clear()
            logger.info("Face registry cleared")
