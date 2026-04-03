# Google Drive Integration Guide for Face Storage

**Vibe Alchemist V2** - Store detected faces in Google Drive automatically

---

## Overview

The system automatically:
1. Saves detected faces to `temp_faces/` folder locally
2. Uploads faces to Google Drive in the background
3. Deletes local copies after successful upload
4. Cleans up all remaining faces ONLY when the system terminates

---

## Step-by-Step Google Drive Setup

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **"Select a project"** → **"New Project"**
3. Name it (e.g., "Vibe Alchemist Faces")
4. Click **"Create"**

---

### Step 2: Enable Google Drive API

1. In your project, go to **"APIs & Services"** → **"Library"**
2. Search for **"Google Drive API"**
3. Click on it and press **"Enable"**

---

### Step 3: Create Service Account

1. Go to **"APIs & Services"** → **"Credentials"**
2. Click **"+ CREATE CREDENTIALS"** → **"Service account"**
3. Fill in:
   - **Service account name**: `vibe-alchemist-faces`
   - **Description**: `Auto-upload faces to Drive`
4. Click **"Create and Continue"**
5. Skip role assignment (not needed)
6. Click **"Done"**

---

### Step 4: Generate Service Account Key

1. In the **Credentials** page, find your service account
2. Click on it → Go to **"Keys"** tab
3. Click **"Add Key"** → **"Create new key"**
4. Choose **JSON** format
5. Click **"Create"**
6. The JSON file will download automatically (e.g., `vibe-alchemist-faces-xxxxx.json`)

---

### Step 5: Create Google Drive Folder

1. Go to [Google Drive](https://drive.google.com/)
2. Create a new folder (e.g., "Vibe Alchemist Faces")
3. Open the folder
4. Copy the **Folder ID** from the URL:
   ```
   https://drive.google.com/drive/folders/1aBC...xyz
                                           ^^^^^^^^^^^
                                           This is the Folder ID
   ```

---

### Step 6: Share Folder with Service Account

1. Open the downloaded JSON key file
2. Find the `client_email` field (looks like: `vibe-alchemist-faces@xxxxx.iam.gserviceaccount.com`)
3. Go back to your Google Drive folder
4. Click **"Share"** → Add the service account email
5. Give it **Editor** access
6. Click **"Send"**

---

### Step 7: Configure Vibe Alchemist

1. Copy the JSON key file to your project directory:
   ```bash
   cp /path/to/downloaded/vibe-alchemist-faces-xxxxx.json "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2/credentials.json"
   ```

2. Edit the `.env` file:
   ```bash
   cd "/home/naman/Projects/Vibe Alchemist/vibe_alchemist_v2"
   nano .env
   ```

3. Add/update these lines:
   ```env
   # Google Drive Configuration
   GDRIVE_CREDENTIALS_FILE=./credentials.json
   GDRIVE_FOLDER_ID=1aBC...xyz  # Replace with your actual Folder ID
   ```

4. Save the file

---

### Step 8: Test the Integration

1. Start the system:
   ```bash
   ./start.sh
   ```

2. Check the backend logs for:
   ```
   INFO | Connected to Google Drive API.
   INFO | Drive Sync started. Interval: 900s
   ```

3. Detect some faces (sit in front of camera)

4. Check drive sync status via API:
   ```bash
   curl http://localhost:8000/api/faces/drive/status
   ```

   Expected response:
   ```json
   {
     "connected": true,
     "last_sync": 1711737600.123,
     "pending_count": 0,
     "uploads": 5
   }
   ```

5. Check your Google Drive folder - faces should appear there!

---

## How It Works

### Face Storage Flow

```
1. Face Detected
   ↓
2. Save to temp_faces/{group}_{id}_{timestamp}.png (local)
   ↓
3. Background worker runs every 15 minutes (configurable)
   ↓
4. Upload all pending files to Google Drive
   ↓
5. Delete local copy after successful upload
   ↓
6. On system termination: Delete ALL remaining faces in temp_faces/
```

### Sync Interval

By default, faces are uploaded every **15 minutes (900 seconds)**.

To change this, add to `.env`:
```env
# Upload every 5 minutes (300 seconds)
FACE_UPLOAD_INTERVAL=300
```

### Manual Sync

Trigger immediate upload via API:
```bash
curl -X POST http://localhost:8000/api/faces/sync
```

---

## Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GDRIVE_CREDENTIALS_FILE` | Path to service account JSON key | `./credentials.json` |
| `GDRIVE_FOLDER_ID` | Google Drive folder ID | `None` (local-only mode) |
| `FACE_TEMP_DIR` | Local temp faces directory | `./temp_faces` |
| `FACE_UPLOAD_INTERVAL` | Sync interval in seconds | `900` (15 minutes) |

### Example `.env` Configuration

```env
# Google Drive Integration
GDRIVE_CREDENTIALS_FILE=./credentials.json
GDRIVE_FOLDER_ID=1aBCdefGHIjklMNOpqrSTUvwxYZ

# Local face storage
FACE_TEMP_DIR=./temp_faces

# Upload every 10 minutes
FACE_UPLOAD_INTERVAL=600
```

---

## Troubleshooting

### Issue: "Google Drive credentials not configured"

**Solution:**
- Ensure `credentials.json` exists in the project directory
- Check `.env` has correct `GDRIVE_CREDENTIALS_FILE` path
- Verify file permissions: `chmod 600 credentials.json`

---

### Issue: Faces not uploading to Drive

**Check:**
1. Service account has **Editor** access to the folder
2. Folder ID is correct (copy from URL again)
3. Check backend logs:
   ```bash
   tail -f logs/backend.log
   ```
4. Test API connection:
   ```bash
   curl http://localhost:8000/api/faces/drive/status
   ```

---

### Issue: "Drive Authentication Failed"

**Solution:**
1. Re-download the service account key
2. Ensure Drive API is enabled in Google Cloud Console
3. Check JSON file is valid:
   ```bash
   cat credentials.json | python -m json.tool
   ```

---

### Issue: Local faces not being deleted after upload

**This is expected behavior during runtime!**

Faces are ONLY deleted:
- After successful upload to Drive (individual files)
- When system terminates (all remaining files)

To check pending uploads:
```bash
ls -lh temp_faces/
```

---

## Security Best Practices

### 1. Never Commit Credentials

The `.gitignore` already includes `credentials.json`, but verify:
```bash
git status
# credentials.json should NOT appear
```

### 2. Restrict Service Account Permissions

- Only give **Editor** access to the specific folder
- Do NOT share the entire Drive
- Use folder-level sharing only

### 3. Rotate Keys Periodically

1. Delete old service account key in Google Cloud Console
2. Generate new key
3. Update `credentials.json`
4. Restart the system

### 4. Monitor Upload Activity

Check your Google Drive activity log:
- Go to Drive → Right-click folder → **"View details"**
- See upload timestamps and file names

---

## Local-Only Mode (No Google Drive)

If you don't configure Google Drive, the system runs in **local-only mode**:

- Faces are saved to `temp_faces/` folder
- No automatic uploads
- Faces persist until system termination
- On termination: All faces are deleted

This is fully functional for local use!

---

## Advanced: Custom Upload Organization

Want faces organized by date/group in Drive? The system already uploads with the original filename format:

```
kids_5_1_1711737600.png
youths_25_2_1711737700.png
adults_30_3_1711737800.png
```

Format: `{group}_{age}_{face_id}_{timestamp}.png`

You can create Drive filters/rules to auto-organize if needed.

---

## Quick Reference Commands

```bash
# Check sync status
curl http://localhost:8000/api/faces/drive/status

# Trigger manual sync
curl -X POST http://localhost:8000/api/faces/sync

# View pending faces (not yet uploaded)
ls -lh temp_faces/

# View backend logs
tail -f logs/backend.log

# Restart system (triggers cleanup)
./stop.sh && ./start.sh
```

---

## Summary

✅ **Setup Time:** ~10 minutes
✅ **Required:** Google Cloud account, Drive API enabled
✅ **Automatic:** Background uploads every 15 minutes
✅ **Safe:** Local faces deleted after successful upload
✅ **Clean:** All faces deleted on system termination

**Your faces are now backed up to Google Drive!** 🎉

---

*Generated: April 3, 2026*
*Vibe Alchemist V2*
