from fastapi import APIRouter, Request
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger("SettingsRoute")

# In-memory settings storage (in production, persist to .env or database)
settings_store: Dict[str, Any] = {
    "auto_playlist": True,
    "face_overlay": True,
    "shuffle_mode": True,
    "privacy_mode": False,
}

# Settings schema validation
VALID_SETTINGS = {
    "auto_playlist": bool,
    "face_overlay": bool,
    "shuffle_mode": bool,
    "privacy_mode": bool,
}

@router.get("/")
@router.get("")
async def get_settings():
    """Returns all current settings."""
    return {"ok": True, "settings": settings_store}

@router.post("/")
@router.post("")
async def save_settings(request: Request):
    """
    Save settings.
    
    Expects JSON body with settings to update:
    {
        "settings": {
            "auto_playlist": true,
            "face_overlay": false,
            ...
        }
    }
    """
    global settings_store
    
    try:
        body = await request.json()
        new_settings = body.get("settings", {})
        
        if not isinstance(new_settings, dict):
            return {"ok": False, "error": "Settings must be an object"}
        
        # Validate and update settings
        updated = {}
        for key, value in new_settings.items():
            if key not in VALID_SETTINGS:
                logger.warning(f"Unknown setting: {key}")
                continue
            
            expected_type = VALID_SETTINGS[key]
            if not isinstance(value, expected_type):
                logger.warning(f"Invalid type for {key}: expected {expected_type}, got {type(value)}")
                continue
            
            settings_store[key] = value
            updated[key] = value
            logger.info(f"Setting updated: {key} = {value}")
        
        return {"ok": True, "updated": updated, "settings": settings_store}
    
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return {"ok": False, "error": str(e)}

@router.get("/{key}")
async def get_setting(key: str):
    """Get a specific setting by key."""
    if key not in settings_store:
        return {"ok": False, "error": f"Setting '{key}' not found"}
    return {"ok": True, "key": key, "value": settings_store[key]}

@router.post("/{key}")
async def update_setting(key: str, request: Request):
    """Update a specific setting."""
    global settings_store
    
    if key not in VALID_SETTINGS:
        return {"ok": False, "error": f"Unknown setting: {key}"}
    
    try:
        body = await request.json()
        value = body.get("value")
        expected_type = VALID_SETTINGS[key]
        
        if not isinstance(value, expected_type):
            return {"ok": False, "error": f"Invalid type for {key}"}
        
        settings_store[key] = value
        logger.info(f"Setting updated: {key} = {value}")
        
        return {"ok": True, "key": key, "value": value}
    
    except Exception as e:
        logger.error(f"Error updating setting {key}: {e}")
        return {"ok": False, "error": str(e)}
