from fastapi import APIRouter
import logging
import os

router = APIRouter(prefix="/faces", tags=["faces"])
logger = logging.getLogger("FacesRoute")

# Global references - set by api_server during startup
refs = {"face_registry": None, "face_vault": None}

def set_refs(face_registry, face_vault):
    """Set references (called by api_server during startup)."""
    refs["face_registry"] = face_registry
    refs["face_vault"] = face_vault

@router.get("")
async def list_faces():
    """Returns detailed face summary stats including per-face details and camera tracking."""
    face_registry = refs.get("face_registry")
    if face_registry:
        summary = face_registry.get_summary()
        # Add detailed face list
        detailed_faces = []
        with face_registry.lock:
            for fid, data in face_registry.known_faces.items():
                detailed_faces.append({
                    'id': fid,
                    'group': data.get('group', 'unknown'),
                    'age': data.get('age', 'unknown'),
                    'cameras': list(data.get('cam_ids', set())),
                    'last_seen': data.get('last_seen', 0)
                })
        summary['faces'] = detailed_faces
        summary['saved_count'] = face_registry.get_saved_count()
        return summary
    return {"total_unique": 0, "by_group": {"kids": 0, "youths": 0, "adults": 0, "seniors": 0}, "faces": []}

@router.get("/drive/status")
async def drive_status():
    """Returns Drive sync status and configuration info."""
    face_vault = refs.get("face_vault")
    if face_vault:
        status = face_vault.get_status()
        # Add configuration diagnostics
        creds_path = face_vault.creds_file
        creds_exists = os.path.exists(creds_path) if creds_path else False
        status.update({
            "configured": face_vault.drive_folder_id is not None and creds_exists,
            "credentials_file": creds_path or "not set",
            "credentials_exist": creds_exists,
            "folder_id_configured": face_vault.drive_folder_id is not None and face_vault.drive_folder_id != "",
        })
        return status
    return {
        "connected": False,
        "last_sync": None,
        "pending_count": 0,
        "configured": False,
        "error": "FaceVault not initialized"
    }

@router.get("/drive/test")
async def test_drive_connection():
    """
    Tests Google Drive connection and returns detailed diagnostics.
    Use this after setting up credentials.json to verify everything works.
    """
    face_vault = refs.get("face_vault")
    if not face_vault:
        return {"ok": False, "error": "FaceVault not initialized"}

    result = {
        "ok": False,
        "details": {}
    }

    # Check 1: Credentials file exists
    creds_path = face_vault.creds_file
    result["details"]["credentials_file"] = creds_path or "not set"
    if not creds_path or not os.path.exists(creds_path):
        result["error"] = f"Credentials file not found: {creds_path or 'not set'}"
        result["details"]["fix"] = "Download service account JSON key from Google Cloud Console and save as credentials.json in project root"
        return result

    # Check 2: Credentials file is valid JSON
    try:
        import json
        with open(creds_path) as f:
            creds_data = json.load(f)
        result["details"]["service_account_email"] = creds_data.get("client_email", "unknown")
        result["details"]["project_id"] = creds_data.get("project_id", "unknown")
    except json.JSONDecodeError as e:
        result["error"] = f"Invalid JSON in credentials file: {e}"
        result["details"]["fix"] = "Re-download the service account key JSON from Google Cloud Console"
        return result
    except Exception as e:
        result["error"] = f"Cannot read credentials file: {e}"
        return result

    # Check 3: Drive library installed
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        result["details"]["libraries"] = "installed"
    except ImportError:
        result["error"] = "Google Drive Python libraries not installed"
        result["details"]["fix"] = "pip install google-auth google-api-python-client"
        return result

    # Check 4: Authenticate
    try:
        scopes = ['https://www.googleapis.com/auth/drive.file']
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
        service = build('drive', 'v3', credentials=creds)
        result["details"]["auth"] = "success"
    except Exception as e:
        result["error"] = f"Authentication failed: {e}"
        result["details"]["fix"] = "Check that the service account key is valid and not revoked"
        return result

    # Check 5: Folder ID is set
    folder_id = face_vault.drive_folder_id
    result["details"]["folder_id"] = folder_id or "not set"
    if not folder_id:
        result["error"] = "GDRIVE_FOLDER_ID not configured in .env"
        result["details"]["fix"] = "Set GDRIVE_FOLDER_ID in .env to your Google Drive folder ID (the long string in the folder URL)"
        return result

    # Check 6: Can access the folder
    try:
        folder_info = service.files().get(fileId=folder_id, fields='id,name').execute()
        result["details"]["folder_name"] = folder_info.get("name", "unknown")
        result["details"]["folder_access"] = "success"
    except Exception as e:
        result["error"] = f"Cannot access Drive folder: {e}"
        result["details"]["fix"] = "Share the Google Drive folder with the service account email (Editor access). Find the email in credentials.json under 'client_email'"
        return result

    # All checks passed
    result["ok"] = True
    result["message"] = (
        f"Google Drive connected! "
        f"Folder: {result['details']['folder_name']} | "
        f"Account: {result['details']['service_account_email']}"
    )
    return result

@router.post("/sync")
async def sync_now():
    """Triggers immediate sync."""
    face_vault = refs.get("face_vault")
    if face_vault:
        face_vault.sync_now()
        return {"ok": True}
    return {"ok": False, "error": "FaceVault not initialized"}
