import os
import time
import threading
import logging
import cv2
import shutil
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

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
        try:
            scopes = ['https://www.googleapis.com/auth/drive.file']
            creds = service_account.Credentials.from_service_account_file(self.creds_file, scopes=scopes)
            self.service = build('drive', 'v3', credentials=creds)
            logger.info("Connected to Google Drive API.")
        except Exception as e:
            logger.error(f"Drive Authentication Failed: {e}")
            self.service = None

    def save_face(self, face_img, face_id, group):
        """Saves a face crop locally."""
        if face_img is None or face_img.size == 0: return
        
        filename = f"{group}_{face_id}_{int(time.time())}.png"
        filepath = self.temp_dir / filename
        
        try:
            cv2.imwrite(str(filepath), face_img)
        except Exception as e:
            logger.error(f"Failed to save face locally: {e}")

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

    def shutdown_push(self):
        """Final sync before exit."""
        logger.info("Final face sync before shutdown...")
        self.sync_now()

    def stop(self):
        self.running = False
        self.shutdown_push()
