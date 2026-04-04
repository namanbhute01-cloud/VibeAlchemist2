import os
import time
import threading
import logging
import cv2
import shutil
import numpy as np
from pathlib import Path

# Google Drive imports — optional (graceful degradation if not installed)
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    _GDRIVE_AVAILABLE = True
except ImportError:
    _GDRIVE_AVAILABLE = False
    service_account = None  # type: ignore
    build = None  # type: ignore
    MediaFileUpload = None  # type: ignore

logger = logging.getLogger("FaceVault")

class FaceVault:
    """
    Manages persistent face storage.
    - Saves high-res crops locally to 'temp_faces/'
    - Background worker uploads to Google Drive every N minutes.
    - Auto-wipes local files after successful sync.
    """
    def __init__(self, temp_dir="temp_faces", drive_folder_id=None, credentials_file="credentials.json", upload_interval=900):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self.drive_folder_id = drive_folder_id or os.getenv("GDRIVE_FOLDER_ID")
        self.creds_file = credentials_file or os.getenv("GDRIVE_CREDENTIALS_FILE")
        self.upload_interval = int(upload_interval) # Seconds (default 15m)
        
        self.service = None
        self.running = False
        self.last_sync = 0
        self.upload_count = 0
        
        # Start background syncer if credentials exist
        if self.drive_folder_id and self.creds_file and os.path.exists(self.creds_file):
            self._authenticate()
            threading.Thread(target=self._sync_loop, daemon=True).start()
        else:
            logger.warning("Google Drive credentials not configured. Running in local-only mode.")

    def _authenticate(self):
        if not _GDRIVE_AVAILABLE:
            logger.warning("Google Drive libraries not installed — Drive sync disabled")
            self.service = None
            return
        try:
            scopes = ['https://www.googleapis.com/auth/drive.file']
            creds = service_account.Credentials.from_service_account_file(self.creds_file, scopes=scopes)
            self.service = build('drive', 'v3', credentials=creds)
            logger.info("Connected to Google Drive API.")
        except Exception as e:
            logger.error(f"Drive Authentication Failed: {e}")
            self.service = None

    def save_face(self, face_img, face_id, group, quality=0.0, age=None):
        """
        Save a face crop locally with quality metadata.

        Args:
            face_img: Face image to save
            face_id: Unique face identifier
            group: Age group (kids/youths/adults/seniors)
            quality: Detection quality score (0.0-1.0)
            age: Estimated age
            force_save: If True, save even if already exists (default False)
        """
        if face_img is None:
            logger.warning(f"Cannot save face {face_id}: image is None")
            return False
        if face_img.size == 0:
            logger.warning(f"Cannot save face {face_id}: image is empty")
            return False

        # Check if this face_id has already been saved
        existing = list(self.temp_dir.glob(f"*_{face_id}_*.png"))
        if existing:
            logger.debug(f"Face {face_id} already saved, skipping duplicate")
            return False

        # Include quality and age in filename for metadata
        quality_str = f"{quality:.2f}" if quality else "0.00"
        age_str = str(age) if age is not None else "unknown"
        filename = f"{group}_{face_id}_q{quality_str}_age{age_str}_{int(time.time())}.png"
        filepath = self.temp_dir / filename

        try:
            # Ensure face_img is contiguous
            if not face_img.flags['C_CONTIGUOUS']:
                face_img = np.ascontiguousarray(face_img)

            success = cv2.imwrite(str(filepath), face_img)
            if success:
                logger.info(
                    f"Saved face: {face_id} | "
                    f"Group: {group} | Quality: {quality:.2f} | Age: {age} | "
                    f"Size: {face_img.shape[0]}x{face_img.shape[1]}"
                )
                return True
            else:
                logger.error(f"cv2.imwrite failed for {filepath}")
                return False
        except Exception as e:
            logger.error(f"Failed to save face {face_id}: {e}")
            return False

    def cleanup(self):
        """
        Delete all files in temp_faces directory and remove the directory.
        IMPORTANT: This should ONLY be called on shutdown/termination.
        Do NOT call this during runtime - it will delete all detected faces!
        """
        if not self.temp_dir.exists():
            logger.info("temp_faces directory does not exist, nothing to clean")
            return

        logger.warning("CLEANUP CALLED - This will delete ALL faces in temp_faces (should only happen on termination)")

        try:
            # Delete all image files
            files = list(self.temp_dir.glob("*.png")) + list(self.temp_dir.glob("*.jpg"))
            deleted = 0
            for f in files:
                try:
                    f.unlink()
                    deleted += 1
                except Exception as e:
                    logger.error(f"Failed to delete {f}: {e}")

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} face(s) from temp_faces on termination")

            # Remove the directory itself if empty
            try:
                remaining = list(self.temp_dir.iterdir())
                if not remaining:
                    self.temp_dir.rmdir()
                    logger.info("Removed empty temp_faces directory on termination")
                else:
                    logger.warning(f"temp_faces not empty after cleanup: {remaining}")
            except Exception as e:
                logger.error(f"Failed to remove temp_faces directory: {e}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

    def shutdown_push(self):
        """Final sync before exit, then cleanup."""
        logger.info("Final face sync before shutdown...")
        self.sync_now()
        # Note: We don't cleanup here because user might want to keep faces
        # Call cleanup() explicitly if you want to delete on shutdown

    def _sync_loop(self):
        self.running = True
        logger.info(f"Drive Sync started. Interval: {self.upload_interval}s")
        
        while self.running:
            time.sleep(10) # Check every 10s
            if time.time() - self.last_sync > self.upload_interval:
                self.sync_now()

    def sync_now(self):
        """Triggers an immediate upload cycle."""
        if not self.service: return
        
        files = list(self.temp_dir.glob("*.png"))
        if not files: return
        
        logger.info(f"Starting Drive Sync: {len(files)} files pending...")
        uploaded = 0
        
        for f in files:
            try:
                file_metadata = {'name': f.name, 'parents': [self.drive_folder_id]}
                media = MediaFileUpload(str(f), mimetype='image/png')
                
                self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                
                # Delete local after success
                f.unlink()
                uploaded += 1
            except Exception as e:
                logger.error(f"Failed to upload {f.name}: {e}")
        
        self.last_sync = time.time()
        self.upload_count += uploaded
        logger.info(f"Drive Sync Complete. Uploaded: {uploaded}/{len(files)}")

    def get_status(self) -> dict:
        pending = len(list(self.temp_dir.glob("*.png"))) if self.temp_dir.exists() else 0
        return {
            "connected": self.service is not None,
            "last_sync": self.last_sync,
            "pending_count": pending,
            "uploads": self.upload_count
        }

    def stop(self):
        self.running = False
        self.shutdown_push()
