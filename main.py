import uvicorn
import os
import sys
import signal
from dotenv import load_dotenv

# Suppress noisy low-level library warnings (NNPACK, etc.)
os.environ["nnpack_limit"] = "0"
os.environ["OMP_NUM_THREADS"] = "1"

def cleanup_temp_faces(signum=None, frame=None):
    """Cleanup temp_faces directory on exit."""
    import shutil
    from pathlib import Path
    
    temp_dir = Path(os.getenv("FACE_TEMP_DIR", "temp_faces"))
    if temp_dir.exists():
        try:
            files = list(temp_dir.glob("*.png"))
            deleted = 0
            for f in files:
                try:
                    f.unlink()
                    deleted += 1
                except Exception as e:
                    print(f"Failed to delete {f}: {e}")
            if deleted > 0:
                print(f"\n✓ Cleaned up {deleted} face(s) from temp_faces")
        except Exception as e:
            print(f"Cleanup error: {e}")
    
    if signum is not None:
        sys.exit(0)

# Register signal handlers for cleanup
signal.signal(signal.SIGINT, cleanup_temp_faces)
signal.signal(signal.SIGTERM, cleanup_temp_faces)

if __name__ == "__main__":
    load_dotenv()

    # Configuration
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    reload = os.getenv("DEBUG", "false").lower() == "true"  # Disable reload for proper signal handling

    print(f"--- VIBE ALCHEMIST V2 STARTING ON {host}:{port} ---")
    print("--- Press Ctrl+C to stop and cleanup temp_faces ---")

    try:
        uvicorn.run(
            "api.api_server:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info"
        )
    finally:
        # Ensure cleanup on any exit
        cleanup_temp_faces()
