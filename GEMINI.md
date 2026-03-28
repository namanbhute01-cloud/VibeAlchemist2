# Project: Vibe Alchemist V2 Integration Rules

1. **Environment & Network Standards**
   - **Rule**: Enforce 127.0.0.1 over localhost for all CORS and Redirect URI configurations.
   - **Backend**: Update CORSMiddleware in FastAPI to allow `http://127.0.0.1:5173` and `http://127.0.0.1:8080`.
   - **Frontend**: Set `VITE_API_URL` to `http://127.0.0.1:8080`.

2. **Spotify API 2026 Compliance**
   - **Target**: `spotify_client.py` (if applicable) or any Spotify integration.
   - **Update**: Replace all calls to `playlists/{id}/tracks` with `playlists/{id}/items` to avoid 403 errors.
   - **Scope Check**: Ensure `user-read-private` and `user-read-playback-state` are requested to enable Audio Feature analysis.

3. **Inference Optimization**
   - **Logic**: Add a "Debounce" service to the backend.
   - **Instruction**: Do not trigger a Spotify search on every frame. Only trigger when `detected_emotion` changes and stays consistent for 120 frames (approx 2 seconds).

4. **WebSocket Implementation**
   - **Action**: Create a `/ws/vibe-stream` endpoint in FastAPI.
   - **Payload**: Send a JSON object: `{ "emotion": string, "spotify_ready": boolean, "suggested_vibe": float }`.

5. **Error Handling**
   - **Action**: If Google Drive credentials are missing (as seen in logs), suppress the warning and default to MemoryCache instead of attempting to write to a non-existent cloud path.
