import numpy as np
import time
import logging
from numpy.linalg import norm

logger = logging.getLogger("FaceRegistry")

class FaceRegistry:
    """
    Manages known face identities using ArcFace embeddings.
    Prevents duplicate detection of the same person across frames and cameras.
    """
    def __init__(self, threshold=0.65, prune_interval=3600):
        self.threshold = threshold
        self.prune_interval = prune_interval
        # id -> {'embedding': np.array, 'group': str, 'last_seen': float, 'cam_id': int}
        self.known_faces = {}
        self.last_prune = time.time()

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
        # Simple ID generation
        new_id = f"face_{len(self.known_faces) + 1}_{int(time.time())}"
        
        self.known_faces[new_id] = {
            'embedding': embedding,
            'group': group,
            'last_seen': time.time(),
            'cam_id': cam_id,
            'first_seen': time.time()
        }
        logger.info(f"New Identity Registered: {new_id} (Group: {group}, Cam: {cam_id})")
        return new_id

    def update(self, face_id, cam_id=None):
        """Updates the last_seen timestamp for a known face."""
        if face_id in self.known_faces:
            self.known_faces[face_id]['last_seen'] = time.time()
            if cam_id is not None:
                self.known_faces[face_id]['cam_id'] = cam_id
            
            # Prune old faces periodically
            if time.time() - self.last_prune > 300:
                self._prune()

    def _prune(self):
        """Removes faces not seen for a long time."""
        now = time.time()
        to_remove = []
        for fid, data in self.known_faces.items():
            if now - data['last_seen'] > self.prune_interval:
                to_remove.append(fid)
        
        for fid in to_remove:
            del self.known_faces[fid]
            logger.debug(f"Pruned stale identity: {fid}")
        
        self.last_prune = now
