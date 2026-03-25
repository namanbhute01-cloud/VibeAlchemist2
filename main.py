import uvicorn
import os
from dotenv import load_dotenv

# Suppress noisy low-level library warnings (NNPACK, etc.)
os.environ["nnpack_limit"] = "0"
os.environ["OMP_NUM_THREADS"] = "1" 

if __name__ == "__main__":
    load_dotenv()
    
    # Configuration
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    reload = os.getenv("DEBUG", "true").lower() == "true"
    
    print(f"--- VIBE ALCHEMIST V2 STARTING ON {host}:{port} ---")
    
    uvicorn.run(
        "api.api_server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
