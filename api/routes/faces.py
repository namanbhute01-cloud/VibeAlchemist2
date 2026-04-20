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
    Supports both Service Account and OAuth2 (User) credentials.
    """
    face_vault = refs.get("face_vault")
    if not face_vault:
        return {"ok": False, "error": "FaceVault not initialized"}

    result = {
        "ok": False,
        "details": {
            "token_file": face_vault.token_file,
            "creds_file": face_vault.creds_file,
            "folder_id": face_vault.drive_folder_id
        }
    }

    # Check 1: Do we have ANY credential file?
    has_token = os.path.exists(face_vault.token_file)
    has_creds = os.path.exists(face_vault.creds_file)
    result["details"]["token_exists"] = has_token
    result["details"]["creds_exists"] = has_creds

    if not has_token and not has_creds:
        result["error"] = "No Google Drive credentials found (token.json or credentials.json)"
        result["details"]["fix"] = "Run 'bash setup-drive.sh' to authenticate."
        return result

    # Check 2: Drive library installed
    try:
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        result["details"]["libraries"] = "installed"
    except ImportError:
        result["error"] = "Google Drive Python libraries not installed"
        result["details"]["fix"] = "pip install google-auth google-api-python-client google-auth-oauthlib"
        return result

    # Check 3: Authenticate and Test Access
    try:
        # This re-uses the internal logic but captures errors for the UI
        face_vault._authenticate()
        if not face_vault.service:
            result["error"] = "Authentication failed (check logs for details)"
            return result
        
        result["details"]["auth"] = "success"
        
        # Check 4: Folder ID is set
        folder_id = face_vault.drive_folder_id
        if not folder_id:
            result["error"] = "GDRIVE_FOLDER_ID not configured in .env"
            return result

        # Check 5: Can access the folder
        folder_info = face_vault.service.files().get(fileId=folder_id, fields='id,name').execute()
        result["details"]["folder_name"] = folder_info.get("name", "unknown")
        result["details"]["folder_access"] = "success"
        
        # All checks passed
        result["ok"] = True
        result["message"] = f"Connected! Folder: {result['details']['folder_name']}"
        return result

    except Exception as e:
        result["error"] = f"Drive access test failed: {e}"
        return result

@router.post("/sync")
async def sync_now():
    """Triggers immediate sync."""
    face_vault = refs.get("face_vault")
    if face_vault:
        face_vault.sync_now()
        return {"ok": True}
    return {"ok": False, "error": "FaceVault not initialized"}
