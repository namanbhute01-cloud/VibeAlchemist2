"""
Centralized Environment Variable Manager

Handles reading, updating, and persisting environment variables to .env file.
All settings changes from the UI should go through this module to ensure
proper synchronization between the application state and configuration files.
"""

import os
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv

logger = logging.getLogger("EnvManager")

# Thread lock for file operations
_file_lock = threading.Lock()

# Path to .env file (resolved once at module load)
ENV_PATH = Path(__file__).parent.parent / ".env"

# Schema for all known environment variables with type validation and metadata
ENV_SCHEMA = {
    # API Server
    "API_HOST": {"type": str, "default": "0.0.0.0", "category": "system"},
    "API_PORT": {"type": int, "default": 8000, "category": "system"},
    "DEBUG": {"type": bool, "default": False, "category": "system"},
    
    # Camera
    "CAMERA_SOURCES": {"type": str, "default": "0", "category": "cameras"},
    "TARGET_HEIGHT": {"type": int, "default": 720, "category": "cameras"},
    "FRAME_RATE_LIMIT": {"type": int, "default": 15, "category": "cameras"},
    
    # Vision & Models
    "MODELS_DIR": {"type": str, "default": "models", "category": "detection"},
    "FACE_DETECTION_CONF": {"type": float, "default": 0.5, "category": "detection"},
    "PERSON_DETECTION_CONF": {"type": float, "default": 0.4, "category": "detection"},
    "FACE_SIMILARITY_THRESHOLD": {"type": float, "default": 0.65, "category": "detection"},
    
    # Face Vault & Storage
    "FACE_TEMP_DIR": {"type": str, "default": "temp_faces", "category": "system"},
    "GDRIVE_FOLDER_ID": {"type": str, "default": "", "category": "system", "sensitive": True},
    "GDRIVE_CREDENTIALS_FILE": {"type": str, "default": "credentials.json", "category": "system"},
    "DRIVE_UPLOAD_INTERVAL": {"type": int, "default": 900, "category": "system"},
    
    # Music Player
    "ROOT_MUSIC_DIR": {"type": str, "default": "./OfflinePlayback", "category": "music"},
    "DEFAULT_VOLUME": {"type": int, "default": 70, "category": "music"},
    "SHUFFLE_MODE": {"type": bool, "default": True, "category": "music"},
    
    # UI Settings
    "AUTO_PLAYLIST": {"type": bool, "default": True, "category": "ui"},
    "FACE_OVERLAY": {"type": bool, "default": True, "category": "ui"},
    "PRIVACY_MODE": {"type": bool, "default": False, "category": "ui"},
    
    # Performance
    "OMP_NUM_THREADS": {"type": int, "default": 1, "category": "system"},
    "NNPACK_LIMIT": {"type": int, "default": 0, "category": "system"},
}


def _parse_value(value_str: str, expected_type: type) -> Any:
    """Parse a string value to the expected type."""
    value_str = value_str.strip()
    
    if expected_type == bool:
        return value_str.lower() in ("true", "1", "yes", "on")
    elif expected_type == int:
        try:
            return int(value_str)
        except ValueError:
            return None
    elif expected_type == float:
        try:
            return float(value_str)
        except ValueError:
            return None
    else:
        return value_str


def _format_value(value: Any) -> str:
    """Format a value for writing to .env file."""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def load_all_settings() -> Dict[str, Any]:
    """
    Load all settings from .env file with defaults from schema.
    Returns a dict with all known settings.
    """
    settings = {}
    
    # Initialize with defaults from schema
    for key, schema in ENV_SCHEMA.items():
        settings[key] = schema["default"]
    
    # Load from .env file if it exists
    if not ENV_PATH.exists():
        logger.warning(f".env file not found at {ENV_PATH}, using defaults")
        return settings
    
    try:
        with open(ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                if "=" not in line:
                    continue
                
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                
                # Check if this is a known setting
                if key in ENV_SCHEMA:
                    expected_type = ENV_SCHEMA[key]["type"]
                    parsed = _parse_value(value, expected_type)
                    if parsed is not None:
                        settings[key] = parsed
                    else:
                        logger.warning(f"Failed to parse {key}={value} as {expected_type}")
                else:
                    # Store unknown settings as strings
                    settings[key] = value
        
        logger.info(f"Loaded {len(settings)} settings from .env")
    except Exception as e:
        logger.error(f"Error loading settings from .env: {e}")
    
    return settings


def save_settings_to_env(settings: Dict[str, Any]) -> bool:
    """
    Persist settings to .env file.
    Only updates keys that are in the settings dict.
    Preserves comments, blank lines, and section headers.
    Thread-safe operation.
    """
    if not settings:
        return True

    with _file_lock:
        try:
            # Read existing .env
            if not ENV_PATH.exists():
                logger.error(f".env file not found at {ENV_PATH}")
                return False

            with open(ENV_PATH, "r") as f:
                lines = f.readlines()

            # Track which settings we've updated
            updated_keys = set()

            # Update existing lines — match "KEY =" or "KEY=" (with optional spaces)
            new_lines = []
            for line in lines:
                stripped = line.strip()
                updated = False

                # Check if this line matches a setting we're updating
                for key, value in settings.items():
                    # Match "KEY=" or "KEY =" patterns
                    if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                        formatted_value = _format_value(value)
                        new_lines.append(f"{key}={formatted_value}\n")
                        updated_keys.add(key)
                        logger.debug(f"Updated {key}={formatted_value} in .env")
                        updated = True
                        break

                if not updated:
                    new_lines.append(line)

            # Add any new settings that weren't in .env
            for key, value in settings.items():
                if key not in updated_keys and key in ENV_SCHEMA:
                    formatted_value = _format_value(value)
                    new_lines.append(f"{key}={formatted_value}\n")
                    logger.info(f"Added {key}={formatted_value} to .env")

            # Write back to .env
            with open(ENV_PATH, "w") as f:
                f.writelines(new_lines)

            # Reload environment variables for current process
            load_dotenv(ENV_PATH, override=True)

            logger.info(f"Persisted {len(settings)} settings to .env")
            return True

        except Exception as e:
            logger.error(f"Error saving settings to .env: {e}")
            return False


def update_setting(key: str, value: Any) -> tuple[bool, Optional[str]]:
    """
    Update a single setting and persist to .env.
    Returns (success, error_message).
    """
    if key not in ENV_SCHEMA:
        return False, f"Unknown setting: {key}"
    
    schema = ENV_SCHEMA[key]
    expected_type = schema["type"]
    
    # Type validation
    if not isinstance(value, expected_type):
        # Try to coerce
        try:
            if expected_type == bool:
                value = bool(value)
            elif expected_type == int:
                value = int(value)
            elif expected_type == float:
                value = float(value)
        except (ValueError, TypeError):
            return False, f"Invalid type for {key}: expected {expected_type}, got {type(value)}"
    
    # Save to .env
    success = save_settings_to_env({key: value})
    
    if success:
        logger.info(f"Setting updated: {key} = {value}")
        return True, None
    else:
        return False, f"Failed to persist {key} to .env"


def get_setting(key: str) -> tuple[bool, Any]:
    """
    Get a single setting value.
    Returns (found, value).
    """
    if key not in ENV_SCHEMA:
        return False, None
    
    settings = load_all_settings()
    return True, settings.get(key)


def get_all_env_vars() -> list[Dict[str, Any]]:
    """
    Get all environment variables with their metadata.
    Returns list of dicts with key, value, masked, category.
    """
    settings = load_all_settings()
    result = []
    
    for key, schema in ENV_SCHEMA.items():
        value = settings.get(key, schema["default"])
        result.append({
            "key": key,
            "value": _format_value(value),
            "masked": schema.get("sensitive", False),
            "category": schema.get("category", "system"),
        })
    
    return result


def get_env_vars_by_category(category: str) -> list[Dict[str, Any]]:
    """Get environment variables filtered by category."""
    all_vars = get_all_env_vars()
    return [v for v in all_vars if v["category"] == category]
