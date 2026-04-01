import numpy as np
import time
import logging
import threading
from numpy.linalg import norm

logger = logging.getLogger("FaceRegistry")

class FaceRegistry:
    """
    Manages known face identities using ArcFace embeddings.
    Prevents duplicate detection of the same person across frames AND cameras.
    Same person on multiple cameras = single identity.
    Includes age in face ID for better identification.
    """
    def __init__(self, threshold=0.50, prune_interval=3600):
        self.threshold = threshold  # Lowered to 0.50 for better cross-camera matching
        self.prune_interval = prune_interval
        # id -> {'embedding': np.array, 'group': str, 'age': int, 'last_seen': float, 'cam_ids': set}
        self.known_faces = {}
        # Track which faces have been saved to vault (to avoid duplicates)
        self.saved_faces = set()
        self.last_prune = time.time()
        self.lock = threading.Lock()
        # Counter for unique face IDs
        self.face_counter = 0

    def _cosine_similarity(self, emb1, emb2):
        """Calculates cosine similarity between two vectors."""
        if emb1 is None or emb2 is None:
            return 0.0
        return np.dot(emb1, emb2) / (norm(emb1) * norm(emb2))

    def is_known(self, embedding, age=None):
        """
        Checks if the embedding matches any known face.
        Now checks across ALL cameras for cross-camera deduplication.
        Returns: (face_id, similarity, age) if found, else (None, 0.0, None)
        """
        with self.lock:
            best_sim = 0.0
            best_id = None
            best_age = None

            for fid, data in self.known_faces.items():
                sim = self._cosine_similarity(embedding, data['embedding'])
                if sim > best_sim:
                    best_sim = sim
                    best_id = fid
                    best_age = data.get('age')

            if best_sim > self.threshold:
                return best_id, best_sim, best_age

            return None, 0.0, None

    def register(self, embedding, group, cam_id, age=None):
        """
        Registers a new face with age-based naming.
        Returns the new face ID in format: {group}_{age}_{unique_id}
        """
        with self.lock:
            self.face_counter += 1
            # Generate age-inclusive ID
            age_str = str(age) if age is not None else "unknown"
            new_id = f"{group}_{age_str}_{self.face_counter}"

            self.known_faces[new_id] = {
                'embedding': embedding,
                'group': group,
                'age': age,
                'last_seen': time.time(),
                'cam_ids': {cam_id},  # Track all cameras this face appears on
                'first_seen': time.time(),
                'saved': False  # Track if this face has been saved
            }
            logger.info(f"New Identity Registered: {new_id} (Group: {group}, Age: {age}, Cam: {cam_id})")
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
        """Updates the last_seen timestamp and adds camera to the set."""
        with self.lock:
            if face_id in self.known_faces:
                self.known_faces[face_id]['last_seen'] = time.time()
                if cam_id is not None:
                    # Add camera to the set of cameras this face appears on
                    self.known_faces[face_id]['cam_ids'].add(cam_id)

                # Prune old faces periodically
                if time.time() - self.last_prune > 300:
                    self._prune()

    def get_cameras_for_face(self, face_id):
        """Get all cameras where this face has been detected."""
        with self.lock:
            if face_id in self.known_faces:
                return self.known_faces[face_id]['cam_ids'].copy()
            return set()

    def get_summary(self) -> dict:
        """Returns counts of UNIQUE people detected by group."""
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
