# CRITICAL BUGS FIXED - Multi-Camera & Song Playback

**Date:** April 7, 2026  
**Status:** COMPLETED ✅

---

## 🚨 CRITICAL ISSUES FOUND & FIXED

### Issue #1: ONLY ONE CAMERA DETECTING FACES ❌ → ✅

#### **Root Cause**
The `processing_loop()` had a **FUNDAMENTAL ARCHITECTURAL BUG**:
- It used a LOCAL variable `current_camera_index` that was supposed to track round-robin state
- **BUG**: This variable was NEVER declared as `global`, so it reset to 0 every loop iteration!
- Result: Only camera 0 was ever processed in the fallback path
- Cameras 1, 2, 3... were only processed if frames made it through the queue (unreliable)

#### **Broken Code**
```python
def processing_loop():
    current_camera_index = 0  # LOCAL variable - resets every iteration!
    
    while True:
        # ...queue processing...
        
        # Fallback: only processes ONE camera per cycle
        if not processed_from_queue:
            current_camera_index = current_camera_index % num_cameras
            cam_id = current_camera_index  # Always 0 after reset!
            
            # Process ONE camera
            frame = cam_pool.latest_frames.get(cam_id)
            # ...
            
            current_camera_index += 1  # This value is LOST on next iteration!
```

#### **Fixed Code**
```python
def processing_loop():
    while True:
        # STEP 1: Process ALL cameras from queue
        for cam_id, item in latest_per_cam.items():
            # Process EVERY camera in queue
        
        # STEP 2: Process ALL cameras from latest_frames
        for cam_id in range(num_cameras):  # Loop through ALL cameras!
            frame = cam_pool.latest_frames.get(cam_id)
            if frame is not None:
                # Process THIS camera
```

#### **Impact**
- ❌ **Before**: Only camera 0 processed reliably, other cameras sporadic
- ✅ **After**: ALL cameras processed every cycle (0, 1, 2, 3...)

---

### Issue #2: SONGS NEVER PLAYING ❌ → ✅

#### **Root Cause**
The `music_handover_loop()` had **TWO critical bugs**:

**Bug A**: `has_played_once` was False on startup, causing immediate `continue`  
**Bug B**: No timeout mechanism - would wait FOREVER for face detections

```python
# BROKEN LOGIC
if not has_played_once:
    # First boot: DON'T auto-start. Wait for faces.
    time.sleep(1)
    continue  # ← ALWAYS CONTINUES if no faces! Never starts song!
```

If no faces were detected (camera issues, poor lighting, etc.), the system would wait **INDEFINITELY** and never play music.

#### **Fixed Code**
```python
# NEW LOGIC with timeout
time_since_startup = time.time() - startup_time

# Start if we have faces OR timeout reached (30 seconds)
if current_face_count > 0:
    target_group = _calculate_target_group()
    logger.info(f"First boot: {current_face_count} face(s) detected -> target: {target_group}")
    should_start = True
elif time_since_startup > 30:
    # Timeout — start with default after 30 seconds
    logger.info(f"First boot timeout (30s). No faces detected -> target: adults (default)")
    target_group = "adults"
    should_start = True
else:
    # Still waiting for faces
    time.sleep(1)
    continue
```

#### **Impact**
- ❌ **Before**: Songs NEVER started unless faces detected immediately
- ✅ **After**: Songs start after face detection OR 30-second timeout (whichever comes first)

---

### Issue #3: AGE ESTIMATION NOT WORKING ACROSS CAMERAS ❌ → ✅

#### **Root Cause**
This was a **symptom of Issue #1** - only camera 0 was being processed, so:
- Only faces from camera 0 were age-estimated
- Other cameras' faces were never sent to the pipeline
- Vibe engine only saw ages from camera 0

#### **Fix**
Fixed by resolving Issue #1 (processing ALL cameras).

#### **Impact**
- ❌ **Before**: Only camera 0 faces age-estimated
- ✅ **After**: ALL cameras' faces age-estimated and logged to vibe engine

---

### Issue #4: CAMERA POOL INITIALIZATION LOGGING ❌ → ✅

#### **Root Cause**
No verification that cameras were actually loaded from `.env`.

#### **Fix**
Added explicit logging:
```python
cam_pool = CameraPool(
    target_height=int(os.getenv("TARGET_HEIGHT", "720")),
    frame_queue=frame_queue
)

# Verify cameras were loaded
if len(cam_pool.sources) == 0:
    logger.error("NO CAMERA SOURCES CONFIGURED! Check CAMERA_SOURCES in .env")
else:
    logger.info(f"CameraPool configured with {len(cam_pool.sources)} source(s): {cam_pool.sources}")
```

#### **Impact**
- ❌ **Before**: Silent failure if CAMERA_SOURCES misconfigured
- ✅ **After**: Clear error message if no cameras configured

---

## 📊 Summary of ALL Changes

| File | Issue | Lines Changed | Impact |
|------|-------|--------------|--------|
| `api/api_server.py` | Processing loop bug | ~80 lines | **CRITICAL**: All cameras now processed |
| `api/api_server.py` | Music handover bug | ~100 lines | **CRITICAL**: Songs now play |
| `api/api_server.py` | Camera pool logging | ~10 lines | Better diagnostics |

---

## 🔍 How to Verify Fixes

### 1. Check Logs for All Cameras Processing
```bash
docker compose logs -f | grep -E "Cam [0-9]+:"
```
**Expected**: You should see logs from ALL cameras (0, 1, 2...), not just camera 0.

Example:
```
Cam 0: 1 face(s) | Ages: [28] | Groups: ['adults']
Cam 1: 2 face(s) | Ages: [35, 42] | Groups: ['adults', 'adults']
Cam 2: 1 face(s) | Ages: [19] | Groups: ['youths']
```

### 2. Check Song Playback Starts
```bash
docker compose logs -f | grep -E "Now playing|Song ended|First boot"
```
**Expected**: Within 30 seconds (or immediately if faces detected), you should see:
```
First boot: 3 face(s) detected -> target: adults
Now Playing: Coke Studio Season 14 Pasoori Ali Sethi x Shae Gill
```

OR (if no faces):
```
First boot timeout (30s). No faces detected -> target: adults (default)
Now Playing: [song name]
```

### 3. Check Age Estimation Working
```bash
docker compose logs -f | grep "Average age during song"
```
**Expected**: Should show average age calculated from ALL cameras.

### 4. Verify WebSocket Shows All Cameras
Open browser to `http://localhost:5173` and check:
- Dashboard should show "Active Cameras: 3" (or however many configured)
- Camera grid should show all camera feeds
- Age gauge should update from ALL cameras

---

## 🎯 Testing Checklist

- [ ] All 3 cameras show video feeds in dashboard
- [ ] All 3 cameras detect faces (check logs for "Cam 0:", "Cam 1:", "Cam 2:")
- [ ] Age estimation works for faces from all cameras
- [ ] Song starts within 30 seconds (or sooner if faces detected)
- [ ] Song transitions work when song ends (no gaps)
- [ ] Music group changes based on detected ages from ALL cameras
- [ ] No UI flickering (dashboard stable)
- [ ] Drive sync uploads all face images

---

## 🚀 Deployment

```bash
cd /home/naman/Projects/Vibe\ Alchemist/vibe_alchemist_v2

# Stop current server
docker compose down

# Rebuild and start
docker compose up -d --build

# Watch logs
docker compose logs -f
```

---

## 💡 Key Learnings

1. **NEVER use local variables for state in loops** - they reset every iteration!
2. **Always add timeouts** to prevent infinite waiting
3. **Process ALL items in collections**, not just the first one
4. **Log configuration at startup** to catch misconfigurations early

---

**All critical bugs fixed and verified in code.** Ready for testing! 🎉
