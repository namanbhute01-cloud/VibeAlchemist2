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
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    _GDRIVE_AVAILABLE = True
except ImportError:
    _GDRIVE_AVAILABLE = False
    service_account = None  # type: ignore
    Credentials = None  # type: ignore
    Request = None  # type: ignore
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
    def __init__(self, temp_dir="temp_faces", drive_folder_id=None, credentials_file="credentials.json", upload_interval=300):
        """
        Args:
            upload_interval: Seconds between Drive syncs (default 5 minutes, lowered from 15)
        """
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.drive_folder_id = drive_folder_id or os.getenv("GDRIVE_FOLDER_ID")
        self.creds_file = credentials_file or os.getenv("GDRIVE_CREDENTIALS_FILE", "credentials.json")
        self.token_file = os.getenv("GDRIVE_TOKEN_FILE", "token.json")
        self.upload_interval = int(upload_interval)

        self.service = None
        self.running = False
        self.last_sync = 0
        self.upload_count = 0

        # Start background syncer if credentials or token exist
        has_creds = self.creds_file and os.path.exists(self.creds_file)
        has_token = self.token_file and os.path.exists(self.token_file)

        if self.drive_folder_id and (has_creds or has_token):
            self._authenticate()
            threading.Thread(target=self._sync_loop, daemon=True).start()
            logger.info(f"Drive sync configured: every {self.upload_interval}s")
        else:
            logger.warning(
                "Google Drive credentials not configured. "
                "Faces saved locally only. Set GDRIVE_FOLDER_ID + credentials.json/token.json to enable Drive sync."
            )

    def _authenticate(self):
        if not _GDRIVE_AVAILABLE:
            logger.warning("Google Drive libraries not installed — Drive sync disabled")
            self.service = None
            return
        
        scopes = ['https://www.googleapis.com/auth/drive.file']
        creds = None

        try:
            # 1. Try OAuth2 User Token (from setup-drive.sh)
            if os.path.exists(self.token_file):
                try:
                    creds = Credentials.from_authorized_user_file(self.token_file, scopes)
                    if creds and creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                    logger.info("Drive: Using OAuth2 User credentials (token.json)")
                except Exception as e:
                    logger.error(f"Failed to load token.json: {e}")
                    creds = None

            # 2. Fallback to Service Account (from scripts/setup_drive.sh)
            if not creds and os.path.exists(self.creds_file):
                try:
                    # Check if it's a service account or client secret
                    import json
                    with open(self.creds_file) as f:
                        data = json.load(f)
                    
                    if data.get("type") == "service_account":
                        creds = service_account.Credentials.from_service_account_file(self.creds_file, scopes=scopes)
                        logger.info("Drive: Using Service Account credentials (credentials.json)")
                except Exception as e:
                    logger.error(f"Failed to load service account: {e}")

            if creds:
                self.service = build('drive', 'v3', credentials=creds)
                logger.info("Connected to Google Drive API.")
            else:
                logger.error("Drive Authentication Failed: No valid credentials found.")
                self.service = None
        except Exception as e:
            logger.error(f"Drive Authentication Error: {e}")
            self.service = None

    def save_face(self, face_img, face_id, group, quality=0.0, age=None):
        """
        Save a face crop locally with quality metadata.
        DOUBLE-CHECK: Only saves if this face_id hasn't been saved in the last 10 seconds.

        Args:
            face_img: Face image to save
            face_id: Unique face identifier (stable identity ID)
            group: Age group (kids/youths/adults/seniors)
            quality: Detection quality score (0.0-1.0)
            age: Estimated age
        """
        if face_img is None:
            logger.warning(f"Cannot save face {face_id}: image is None")
            return False
        if face_img.size == 0:
            logger.warning(f"Cannot save face {face_id}: image is empty")
            return False

        # FIX: More robust dedup - extract base face_id from timestamp_id if needed
        # face_id could be "adults_25_1_cam0_1712345678" or just "track_0"
        # Extract the identity part (everything before the last timestamp)
        base_face_id = face_id
        parts = str(face_id).rsplit('_', 1)
        if len(parts) == 2 and parts[1].isdigit():
            base_face_id = parts[0]  # Remove trailing timestamp

        # Check if this face_id was recently saved (prevent duplicates within 10s)
        now = int(time.time())
        existing = list(self.temp_dir.glob(f"*{base_face_id}*"))
        if existing:
            # Check if any existing file was saved recently (within 10 seconds)
            for f in existing:
                try:
                    # Extract timestamp from filename: last part after underscore
                    fname_parts = f.stem.rsplit('_', 1)
                    if len(fname_parts) == 2 and fname_parts[1].isdigit():
                        timestamp = int(fname_parts[1])
                        if now - timestamp < 10:
                            logger.debug(f"Face {base_face_id} recently saved ({now - timestamp}s ago), skipping")
                            return False
                except (ValueError, IndexError):
                    pass

        # Include quality and age in filename for metadata
        quality_str = f"{quality:.2f}" if quality else "0.00"
        age_str = str(age) if age is not None else "unknown"
        filename = f"{group}_{face_id}_q{quality_str}_age{age_str}_{now}.png"
        filepath = self.temp_dir / filename

        try:
            # Ensure face_img is contiguous
            if not face_img.flags['C_CONTIGUOUS']:
                face_img = np.ascontiguousarray(face_img)

            success = cv2.imwrite(str(filepath), face_img)
            if success:
                logger.info(
                    f"Saved face: {base_face_id} | "
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
        """Triggers an immediate upload cycle.

        Files uploaded to Google Drive are NEVER deleted from Drive.
        Only local temp_faces files are removed after successful upload.
        On server termination, remaining temp_faces are cleaned up.
        """
        if not self.service:
            logger.info("Drive sync skipped: service not connected")
            return

        # Get ALL image files (png and jpg)
        files = list(self.temp_dir.glob("*.png")) + list(self.temp_dir.glob("*.jpg"))
        if not files:
            logger.info("Drive sync: No pending files")
            return

        logger.info(f"Starting Drive Sync: {len(files)} files pending...")
        uploaded = 0
        failed = 0

        for f in files:
            try:
                # Skip if file is being written (check if file is locked)
                if not os.access(str(f), os.R_OK):
                    logger.debug(f"Skipping {f.name}: file not readable")
                    continue

                file_metadata = {'name': f.name, 'parents': [self.drive_folder_id]}
                media = MediaFileUpload(str(f), mimetype='image/png' if f.suffix == '.png' else 'image/jpeg')

                result = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()

                # File uploaded successfully — delete LOCAL copy only
                # Drive files are NEVER deleted
                f.unlink()
                uploaded += 1
                logger.debug(f"Uploaded to Drive: {f.name} (ID: {result.get('id')})")

            except Exception as e:
                failed += 1
                logger.error(f"Failed to upload {f.name} to Drive: {e}")
                # Keep local file — retry next sync cycle

        self.last_sync = time.time()
        self.upload_count += uploaded
        logger.info(f"Drive Sync Complete. Uploaded: {uploaded}/{len(files)} (failed: {failed}, total: {self.upload_count})")

    def get_status(self) -> dict:
        pending = len(list(self.temp_dir.glob("*.png"))) if self.temp_dir.exists() else 0
        return {
            "connected": self.service is not None,
            "last_sync": self.last_sync,
            "pending_count": pending,
            "uploads": self.upload_count
        }

    def stop(self):
        """Stop the vault and do a final sync with timeout protection."""
        self.running = False
        # Use a thread to enforce timeout on shutdown_push (prevents hanging)
        import threading
        sync_thread = threading.Thread(target=self.shutdown_push, daemon=True)
        sync_thread.start()
        sync_thread.join(timeout=30)  # Max 30 seconds for final sync
        if sync_thread.is_alive():
            logger.warning("Face vault shutdown timed out after 30s — forcing exit")
