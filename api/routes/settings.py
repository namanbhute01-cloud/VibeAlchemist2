from fastapi import APIRouter, Request, HTTPException
import logging
from typing import Optional, Dict, Any
from core import env_manager

router = APIRouter(prefix="/settings", tags=["settings"])
logger = logging.getLogger("SettingsRoute")

@router.get("/")
@router.get("")
async def get_settings():
    """Returns all current settings from .env file."""
    try:
        settings = env_manager.load_all_settings()
        return {"ok": True, "settings": settings}
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
        return {"ok": False, "error": str(e)}

@router.post("/")
@router.post("")
async def save_settings(request: Request):
    """
    Save settings and persist to .env file.
    
    Expects JSON body with settings to update:
    {
        "settings": {
            "AUTO_PLAYLIST": true,
            "FACE_OVERLAY": false,
            ...
        }
    }
    """
    try:
        body = await request.json()
        new_settings = body.get("settings", {})

        if not isinstance(new_settings, dict):
            return {"ok": False, "error": "Settings must be an object"}

        # Validate and update settings using env_manager
        updated = {}
        errors = []
        
        for key, value in new_settings.items():
            # Handle both uppercase and lowercase keys
            normalized_key = key.upper() if key.islower() else key
            
            if normalized_key not in env_manager.ENV_SCHEMA:
                logger.warning(f"Unknown setting: {normalized_key}")
                errors.append(f"Unknown setting: {normalized_key}")
                continue

            success, error = env_manager.update_setting(normalized_key, value)
            if success:
                updated[normalized_key] = value
            else:
                errors.append(error)

        if errors:
            return {
                "ok": len(updated) > 0,
                "updated": updated,
                "errors": errors,
                "settings": env_manager.load_all_settings()
            }

        return {"ok": True, "updated": updated, "settings": env_manager.load_all_settings()}

    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return {"ok": False, "error": str(e)}

@router.get("/env-vars")
async def get_env_vars():
    """Returns all environment variables with metadata for the settings editor."""
    try:
        env_vars = env_manager.get_all_env_vars()
        return {"ok": True, "env_vars": env_vars}
    except Exception as e:
        logger.error(f"Error loading env vars: {e}")
        return {"ok": False, "error": str(e)}

@router.post("/env-vars")
async def update_env_var(request: Request):
    """
    Update a single environment variable and persist to .env.
    
    Expects JSON body:
    {
        "key": "API_PORT",
        "value": "8081"
    }
    """
    try:
        body = await request.json()
        key = body.get("key")
        value = body.get("value")

        if not key:
            return {"ok": False, "error": "Key is required"}

        if key not in env_manager.ENV_SCHEMA:
            return {"ok": False, "error": f"Unknown setting: {key}"}

        # Parse value to correct type
        schema = env_manager.ENV_SCHEMA[key]
        try:
            if schema["type"] == bool:
                value = value.lower() in ("true", "1", "yes", "on") if isinstance(value, str) else bool(value)
            elif schema["type"] == int:
                value = int(value)
            elif schema["type"] == float:
                value = float(value)
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": f"Invalid value for {key}: {e}"}

        success, error = env_manager.update_setting(key, value)
        
        if success:
            return {"ok": True, "key": key, "value": value}
        else:
            return {"ok": False, "error": error}

    except Exception as e:
        logger.error(f"Error updating env var: {e}")
        return {"ok": False, "error": str(e)}

@router.get("/{key}")
async def get_setting(key: str):
    """Get a specific setting by key."""
    # Normalize key to uppercase
    key = key.upper()
    
    found, value = env_manager.get_setting(key)
    if not found:
        return {"ok": False, "error": f"Setting '{key}' not found"}
    return {"ok": True, "key": key, "value": value}

@router.post("/{key}")
async def update_setting(key: str, request: Request):
    """Update a specific setting and persist to .env."""
    # Normalize key to uppercase
    key = key.upper()
    
    try:
        body = await request.json()
        value = body.get("value")

        if value is None:
            return {"ok": False, "error": "Value is required"}

        success, error = env_manager.update_setting(key, value)
        
        if success:
            return {"ok": True, "key": key, "value": value}
        else:
            return {"ok": False, "error": error}

    except Exception as e:
        logger.error(f"Error updating setting {key}: {e}")
        return {"ok": False, "error": str(e)}
