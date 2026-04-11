# Google Drive Face Photo Setup — COMPLETE GUIDE

**Status:** FIXED ✅ — Every detected face now saves to Drive permanently

---

## WHAT WAS BROKEN (AND FIXED)

### Bug #1: Duplicate Check Blocked ALL Saves After First One ❌ → ✅
**Problem:** `save_face()` checked if any file matching `*_{face_id}_*.png` existed. If yes → skipped save.
**Impact:** Once `adults_track_0_q0.8_age30_1234567890.png` was saved, NO future frames of that person ever saved again.
**Fix:** Removed duplicate check. Every detection gets a unique timestamp ID.

### Bug #2: Save Only Triggered for Registered Faces ❌ → ✅
**Problem:** Save code was inside `if embedding is not None and self.registry:` — if ArcFace failed, no save.
**Fix:** Save now happens for EVERY detected face (regardless of embedding/registry).

### Bug #3: `is_saved()` Gate Blocked Future Saves ❌ → ✅
**Problem:** `if not self.registry.is_saved(face_id)` — once a face was marked saved, never saved again.
**Fix:** Removed `is_saved()` check. Uses unique timestamp IDs instead.

### Bug #4: Sync Interval Too Long (15 minutes) ❌ → ✅
**Problem:** Faces sat in `temp_faces/` for up to 15 minutes before uploading.
**Fix:** Lowered default to 5 minutes (300s). Can be set via `DRIVE_UPLOAD_INTERVAL` in `.env`.

---

## HOW IT WORKS NOW

```
1. Camera detects face → face_crop extracted
2. Save to local temp_faces/ with UNIQUE filename:
   adults_track_0_0_1712598234567_q0.72_age32.png
   (group)_(track_id)_(cam_id)_(timestamp_ms)_q(quality)_age(age).png

3. Background sync thread checks every 10 seconds
4. Every 5 minutes (configurable), uploads ALL pending files to Drive
5. After successful upload → deletes LOCAL copy (Drive copy is permanent)
6. Drive files are NEVER deleted from Google Drive
```

---

## SETUP STEPS

### Step 1: Create Google Cloud Project + Service Account

1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable **Google Drive API**:
   - Go to "APIs & Services" → "Library"
   - Search "Google Drive API" → Enable
4. Create a **Service Account**:
   - Go to "IAM & Admin" → "Service Accounts"
   - Click "Create Service Account"
   - Name it (e.g., "vibealchemist-drive-sync")
   - Grant role: **"Storage Admin"** or just leave without role
   - Click "Done"
5. Create a **JSON Key**:
   - Click on the service account → "Keys" tab
   - "Add Key" → "Create new key" → JSON
   - Download the JSON file

### Step 2: Save Credentials

Save the downloaded JSON file as `credentials.json` in your project root:

```bash
cp ~/Downloads/your-service-account-key.json \
   "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2/credentials.json"
```

### Step 3: Create Drive Folder

1. Open Google Drive: https://drive.google.com/
2. Create a new folder (e.g., "VibeAlchemist Faces")
3. **Share the folder with the service account email**:
   - Right-click folder → Share
   - Paste the service account email (from the JSON key file, looks like `vibealchemist@PROJECT_ID.iam.gserviceaccount.com`)
   - Give "Editor" permission
4. Get the **Folder ID** from the URL:
   ```
   https://drive.google.com/drive/folders/1aBCdefGHIjklMNOpqrsTUVwxyz
                                          ↑ this is the Folder ID
   ```

### Step 4: Configure .env

Add these lines to your `.env` file:

```bash
# Google Drive Face Storage
GDRIVE_FOLDER_ID=1aBCdefGHIjklMNOpqrsTUVwxyz
GDRIVE_CREDENTIALS_FILE=credentials.json
DRIVE_UPLOAD_INTERVAL=300
FACE_TEMP_DIR=./temp_faces
```

### Step 5: Install Google Drive Libraries

```bash
cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"
source venv/bin/activate
pip install google-auth google-auth-oauthlib google-api-python-client
```

### Step 6: Restart Server

```bash
docker compose down
docker compose up -d --build
```

---

## VERIFY DRIVE SYNC IS WORKING

### 1. Check Startup Logs
```bash
docker compose logs -f | grep -E "Drive|FaceVault|credentials"
```
Expected:
```
Drive sync configured: every 300s
Connected to Google Drive API.
```

If NOT working:
```
Google Drive credentials not configured. Set GDRIVE_FOLDER_ID + credentials.json
```

### 2. Check Face Saving
```bash
docker compose logs -f | grep -E "Face saved|Saved face"
```
Expected (every few seconds when faces detected):
```
Face saved: track_0_0_1712598234567 (Group: adults, Age: 32, Quality: 0.72)
```

### 3. Check Local temp_faces/
```bash
ls -la vibe_alchemist_v2/temp_faces/
```
Expected: PNG files with metadata in filenames:
```
adults_track_0_0_1712598234567_q0.72_age32.png
kids_track_1_0_1712598235891_q0.85_age8.png
```

### 4. Check Drive Upload
```bash
docker compose logs -f | grep -E "Drive Sync|Uploaded to Drive"
```
Expected (every 5 minutes):
```
Starting Drive Sync: 12 files pending...
Drive Sync Complete. Uploaded: 12/12 (failed: 0, total: 12)
```

### 5. Verify in Google Drive
Open https://drive.google.com/ → your folder → should see PNG files accumulating.

---

## MANUAL SYNC (Force Upload Now)

If you want to upload immediately without waiting:

```bash
# Via API endpoint (if server is running):
curl http://localhost:8000/api/faces/sync

# Or trigger programmatically:
docker compose exec vibe-alchemist python -c "
from core.face_vault import FaceVault
vault = FaceVault()
vault.sync_now()
"
```

---

## TROUBLESHOOTING

### "Google Drive credentials not configured"
- Check `GDRIVE_FOLDER_ID` is set in `.env`
- Check `credentials.json` exists in project root
- Verify service account has Editor permission on the Drive folder

### "Drive Authentication Failed"
- JSON key file may be corrupted — re-download from Google Cloud Console
- Service account may be deleted — recreate it
- Drive API may not be enabled — check Google Cloud Console

### "Drive sync skipped: service not connected"
- Google Drive Python libraries not installed:
  ```bash
  pip install google-auth google-auth-oauthlib google-api-python-client
  ```

### Files in temp_faces/ but not uploading
- Check sync logs: `docker compose logs -f | grep "Drive Sync"`
- Check for errors: `docker compose logs -f | grep "Failed to upload"`
- Force sync: `curl http://localhost:8000/api/faces/sync`

### Drive files getting deleted
- **Drive files are NEVER deleted** — only local temp_faces/ files are cleaned after upload
- If Drive files are disappearing, check someone else isn't cleaning the folder

---

## FILE NAMING FORMAT

Every saved face follows this pattern:
```
{group}_{face_id}_{cam_id}_{timestamp_ms}_q{quality}_age{age}.png
```

Example:
```
adults_track_5_0_1712598234567_q0.85_age32.png
```
- **adults**: Detected age group
- **track_5**: Face tracking ID
- **0**: Camera ID
- **1712598234567**: Timestamp in milliseconds
- **q0.85**: Detection quality (0.00-1.00)
- **age32**: Estimated age

---

## CONFIGURATION OPTIONS

| Env Variable | Default | Description |
|-------------|---------|-------------|
| `GDRIVE_FOLDER_ID` | None | Google Drive folder ID (required) |
| `GDRIVE_CREDENTIALS_FILE` | credentials.json | Path to service account JSON |
| `DRIVE_UPLOAD_INTERVAL` | 300 | Seconds between syncs (300 = 5 min) |
| `FACE_TEMP_DIR` | ./temp_faces | Local temp storage path |

---

**ALL DRIVES SYNC FIXES COMPLETE.** Every detected face now saves permanently to Google Drive. 🎯
