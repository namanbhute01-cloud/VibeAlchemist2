# Blinking Issue Fix Report

## Problem Description
The application was experiencing visible blinking/flickering in the camera feeds and UI components when running.

## Root Causes Identified

### 1. **Camera Feed Blinking** (Primary Issue)
**File:** `frontend/src/components/CameraGrid.tsx`

**Problem:**
- Using `<img>` tag with query parameter `?t=${feedTimestamp}` that refreshed every 30 seconds
- Browser was reloading the entire MJPEG stream causing visible flickers
- No proper loading/error state management

**Fix:**
- Removed timestamp-based refresh (browsers handle MJPEG streams automatically)
- Added proper event listeners for load/error states
- Implemented smooth opacity transitions
- Created dedicated `CameraCard` component with proper state management

### 2. **Frame Race Condition** (Critical Backend Issue)
**File:** `api/api_server.py`

**Problem:**
- `_draw_bounding_boxes()` was modifying `latest_frames` dict while MJPEG endpoint was reading from it
- No thread synchronization between annotation and streaming
- Could serve incomplete/corrupted frames causing visual glitches

**Fix:**
- Added `_frame_lock` threading.Lock() to synchronize frame access
- Wrapped both annotation and streaming code with lock
- Added frame validation (minimum size, proper format)
- Added error handling to prevent crashes on bad frames

### 3. **Camera Pool Thread Safety** (Backend Issue)
**File:** `core/camera_pool.py`

**Problem:**
- No thread locking when storing/retrieving frames
- Could return partially-written frames or None unexpectedly
- No frame validation before returning

**Fix:**
- Added `_frame_lock` to CameraPool class
- Frame storage now uses lock and stores copies
- `get_latest_frame()` now validates frame integrity
- Returns safe copies to prevent mutation issues

### 4. **Aggressive UI Re-animation** (Minor Issue)
**File:** `frontend/src/components/AnimatedCard.tsx`

**Problem:**
- Re-triggered animation EVERY time children changed
- No debouncing - rapid state changes caused flickering
- Too short timeout (50ms) didn't allow smooth transitions

**Fix:**
- Added debouncing with proper cleanup
- Only re-animates if component is already visible
- Increased timeout to 100ms for smoother transitions
- Added proper cleanup on unmount

## Files Modified

1. `frontend/src/components/CameraGrid.tsx` - Complete rewrite of feed handling
2. `api/api_server.py` - Added frame locking and validation
3. `core/camera_pool.py` - Added thread-safe frame access
4. `frontend/src/components/AnimatedCard.tsx` - Reduced aggressive animations

## Testing Instructions

1. **Start the application:**
   ```bash
   ./start.sh  # Development mode
   # or
   ./deploy.sh  # Production mode
   ```

2. **Verify camera feeds:**
   - Check that camera streams load smoothly
   - No flickering when annotations appear
   - Loading states show properly

3. **Check UI components:**
   - Cards should animate in smoothly on first load
   - No rapid re-animations when data updates
   - Smooth transitions throughout

## Expected Results

✅ Camera feeds display continuously without blinking
✅ Face detection annotations appear smoothly
✅ UI components animate gracefully
✅ No race conditions or corrupted frames
✅ Thread-safe frame handling throughout

## Technical Details

### Thread Safety Model
```
Camera Worker Thread → Stores frame (with lock)
                        ↓
Vision Pipeline → Annotates frame (with lock)
                        ↓
MJPEG Endpoint → Reads frame (with lock)
```

### MJPEG Stream Handling
- Browser automatically handles continuous multipart JPEG updates
- No manual refresh needed
- Smooth transitions via CSS opacity

## Backup Files
Original files backed up as:
- `api/api_server.py.backup`
- `core/camera_pool.py.backup`

## Rollback Instructions
If needed, restore original files:
```bash
cp api/api_server.py.backup api/api_server.py
cp core/camera_pool.py.backup core/camera_pool.py
```
