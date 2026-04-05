import uvicorn
import os
import sys
import signal
from dotenv import load_dotenv

# Suppress noisy low-level library warnings (NNPACK, etc.)
os.environ["nnpack_limit"] = "0"
os.environ["OMP_NUM_THREADS"] = "1"

# Track whether cleanup has already run (prevent double/triple cleanup)
_cleanup_done = False

def cleanup_temp_faces(signum=None, frame=None):
    """Cleanup temp_faces directory ONLY on termination (Ctrl+C, SIGTERM, etc.)."""
    global _cleanup_done

    # Idempotent: only run once
    if _cleanup_done:
        return
    _cleanup_done = True

    from pathlib import Path

    temp_dir = Path(os.getenv("FACE_TEMP_DIR", "temp_faces"))
    if temp_dir.exists():
        try:
            # Delete all PNG files
            files = list(temp_dir.glob("*.png"))
            deleted = 0
            for f in files:
                try:
                    f.unlink()
                    deleted += 1
                except Exception as e:
                    print(f"Failed to delete {f}: {e}")

            # Also delete JPG files if any
            jpg_files = list(temp_dir.glob("*.jpg"))
            for f in jpg_files:
                try:
                    f.unlink()
                    deleted += 1
                except Exception as e:
                    print(f"Failed to delete {f}: {e}")

            if deleted > 0:
                print(f"\n✓ Cleaned up {deleted} face(s) from temp_faces on termination")

            # Remove the directory itself if empty
            try:
                if any(temp_dir.iterdir()):
                    print(f"⚠ temp_faces directory still has {len(list(temp_dir.iterdir()))} file(s)")
                else:
                    temp_dir.rmdir()
                    print("✓ Removed empty temp_faces directory")
            except Exception as e:
                print(f"⚠ Could not remove temp_faces directory: {e}")
        except Exception as e:
            print(f"Cleanup error: {e}")
    else:
        print("✓ temp_faces directory does not exist, nothing to clean")

    if signum is not None:
        print("✓ Termination signal received, exiting gracefully...")

# Register signal handlers for cleanup
signal.signal(signal.SIGINT, cleanup_temp_faces)
signal.signal(signal.SIGTERM, cleanup_temp_faces)

if __name__ == "__main__":
    load_dotenv()

    # Configuration
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    # reload=True causes uvicorn to restart on ANY file change (including logs, temp_faces)
    # This causes crashes and UI flickering. Default to False for stability.
    reload = os.getenv("DEBUG", "false").lower() == "true"
    if reload:
        print("WARNING: DEBUG mode with reload enabled — NOT recommended for production")

    print(f"--- VIBE ALCHEMIST V2 STARTING ON {host}:{port} (reload={reload}) ---")
    print("--- Press Ctrl+C to stop and cleanup temp_faces ---")

    try:
        uvicorn.run(
            "api.api_server:app",
            host=host,
            port=port,
            reload=reload,
            # Exclude non-Python files from reload watcher to prevent spurious restarts
            reload_excludes=["logs/*", "temp_faces/*", "*.log", "*.json", "static/*", "frontend/*"] if reload else None,
            log_level="info"
        )
    finally:
        # Ensure cleanup on any exit
        cleanup_temp_faces()
