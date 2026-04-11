#!/usr/bin/env python3
"""
Vibe Alchemist V2 — Detection Flow Validator
Traces the COMPLETE flow: Camera → Processing → Detection → Save → Music
"""
import os
import sys
import json
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("Validator")

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_env():
    """Test 1: Check .env configuration"""
    logger.info("=" * 60)
    logger.info("TEST 1: Environment Configuration")
    logger.info("=" * 60)

    from dotenv import load_dotenv
    load_dotenv()

    issues = []
    
    camera_sources = os.getenv("CAMERA_SOURCES", "0")
    logger.info(f"  CAMERA_SOURCES: {camera_sources}")
    if not camera_sources:
        issues.append("CAMERA_SOURCES not set!")
    
    music_dir = os.getenv("ROOT_MUSIC_DIR", "./OfflinePlayback")
    logger.info(f"  ROOT_MUSIC_DIR: {music_dir}")
    music_path = os.path.abspath(music_dir)
    if not os.path.exists(music_path):
        issues.append(f"Music directory not found: {music_path}")
    else:
        for group in ["kids", "youths", "adults", "seniors"]:
            group_path = os.path.join(music_path, group)
            if os.path.exists(group_path):
                songs = list(os.path.join(group_path, f) for f in os.listdir(group_path) if f.endswith(('.mp3', '.wav', '.flac')))
                logger.info(f"    {group}/: {len(songs)} songs")
            else:
                issues.append(f"Missing music folder: {group}/")
    
    gdrive_id = os.getenv("GDRIVE_FOLDER_ID", "")
    logger.info(f"  GDRIVE_FOLDER_ID: {'SET' if gdrive_id else 'NOT SET'}")
    creds = os.getenv("GDRIVE_CREDENTIALS_FILE", "credentials.json")
    logger.info(f"  GDRIVE_CREDENTIALS_FILE: {creds} ({'EXISTS' if os.path.exists(creds) else 'MISSING'})")

    return issues

def test_music_player():
    """Test 2: Music player initialization"""
    logger.info("=" * 60)
    logger.info("TEST 2: Music Player (AlchemistPlayer)")
    logger.info("=" * 60)

    from core.alchemist_player import AlchemistPlayer
    from dotenv import load_dotenv
    load_dotenv()
    music_dir = os.getenv("ROOT_MUSIC_DIR", "./OfflinePlayback")

    try:
        player = AlchemistPlayer(music_root=music_dir)
        logger.info(f"  Player: RUNNING")
        logger.info(f"  Process: {player.process.pid if player.process else 'None'}")
        status = player.get_status()
        logger.info(f"  Status: {status}")
        
        # Check music folders
        for group in ["kids", "youths", "adults", "seniors"]:
            folder = os.path.join(music_dir, group)
            if os.path.exists(folder):
                songs = list(os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(('.mp3', '.wav', '.flac', '.m4a', '.ogg')))
                logger.info(f"    {group}/: {len(songs)} songs")
                if len(songs) == 0:
                    logger.warning(f"    ⚠ EMPTY FOLDER: {group}/ has no songs!")
        
        player.stop()
        return []
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        return [f"Music player failed: {e}"]

def test_vibe_engine():
    """Test 3: Vibe engine"""
    logger.info("=" * 60)
    logger.info("TEST 3: Vibe Engine")
    logger.info("=" * 60)

    from core.vibe_engine import VibeEngine

    try:
        engine = VibeEngine()
        logger.info(f"  Engine: RUNNING")
        logger.info(f"  Current vibe: {engine.current_vibe}")
        logger.info(f"  Consensus threshold: {engine.consensus_threshold}")
        logger.info(f"  Quality journal: {len(engine.quality_journal)} entries")
        
        # Test detection logging
        engine.log_detection("adults", age=30, quality=0.8, cam_id=0)
        engine.log_detection("adults", age=35, quality=0.7, cam_id=0)
        logger.info(f"  After 2 detections: average_age={engine.average_age}, journal={len(engine.journal)}")
        
        return []
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        return [f"Vibe engine failed: {e}"]

def test_face_vault():
    """Test 4: Face vault"""
    logger.info("=" * 60)
    logger.info("TEST 4: Face Vault")
    logger.info("=" * 60)

    from core.face_vault import FaceVault
    import cv2
    import numpy as np

    try:
        vault = FaceVault(temp_dir="temp_faces")
        logger.info(f"  Vault: RUNNING")
        logger.info(f"  Temp dir: {vault.temp_dir}")
        logger.info(f"  Drive connected: {vault.service is not None}")
        logger.info(f"  Upload interval: {vault.upload_interval}s")

        # Test saving a face
        test_face = np.random.randint(0, 255, (100, 80, 3), dtype=np.uint8)
        result = vault.save_face(test_face, "test_face_001", "adults", quality=0.7, age=30)
        logger.info(f"  Test save result: {result}")

        # Check temp directory
        files = list(vault.temp_dir.glob("*.png"))
        logger.info(f"  Files in temp_faces: {len(files)}")
        if files:
            for f in files[:5]:
                logger.info(f"    {f.name}")
        
        vault.cleanup()
        return []
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        return [f"Face vault failed: {e}"]

def test_vision_pipeline():
    """Test 5: Vision pipeline"""
    logger.info("=" * 60)
    logger.info("TEST 5: Vision Pipeline")
    logger.info("=" * 60)

    from core.vision_pipeline import VisionPipeline
    from core.vibe_engine import VibeEngine
    from core.face_vault import FaceVault
    from core.face_registry import FaceRegistry
    import cv2
    import numpy as np

    try:
        vibe_engine = VibeEngine()
        vault = FaceVault(temp_dir="temp_faces")
        registry = FaceRegistry()
        
        logger.info("  Initializing VisionPipeline (may take 10-30s for model loading)...")
        pipeline = VisionPipeline(models_dir="models", pool=None, engine=vibe_engine, vault=vault, registry=registry)
        logger.info(f"  Pipeline: RUNNING")
        logger.info(f"  Age fusion: {'ENABLED' if pipeline.age_fusion else 'DISABLED'}")
        logger.info(f"  Face quality scorer: {'ENABLED' if pipeline.face_quality_scorer else 'DISABLED'}")
        logger.info(f"  Person model: {'LOADED' if pipeline.person_model else 'FAILED'}")
        logger.info(f"  Face model: {'LOADED' if pipeline.face_model else 'FAILED'}")
        logger.info(f"  Multi-scale: {pipeline.use_multiscale}, scales: {pipeline.scales}")

        # Test with a blank frame (should return no detections)
        blank_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        logger.info("  Testing with blank frame...")
        detections = pipeline.process_frame(blank_frame, cam_id=0)
        logger.info(f"  Blank frame detections: {len(detections)} (expected: 0)")

        # Test with noise frame (may detect false positives)
        noise_frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
        logger.info("  Testing with noise frame...")
        detections = pipeline.process_frame(noise_frame, cam_id=0)
        logger.info(f"  Noise frame detections: {len(detections)}")

        # Check if faces were saved
        files = list(vault.temp_dir.glob("*.png"))
        logger.info(f"  Faces saved to temp: {len(files)}")

        vault.cleanup()
        return []
    except Exception as e:
        logger.error(f"  FAILED: {e}", exc_info=True)
        return [f"Vision pipeline failed: {e}"]

def test_processing_loop():
    """Test 6: Processing loop logic"""
    logger.info("=" * 60)
    logger.info("TEST 6: Processing Loop Logic")
    logger.info("=" * 60)

    from api.api_server import processing_loop, _log_detections, _handle_playback, _draw_bounding_boxes
    from core.vibe_engine import VibeEngine
    import numpy as np

    issues = []

    try:
        vibe_engine = VibeEngine()

        # Test _log_detections
        test_detections = [
            {'group': 'adults', 'age': 30, 'quality': 0.8, 'cam_id': 0},
            {'group': 'kids', 'age': 8, 'quality': 0.6, 'cam_id': 0},
        ]
        _log_detections(test_detections, vibe_engine, 0)
        logger.info(f"  After _log_detections: average_age={vibe_engine.average_age}")
        logger.info(f"  Quality journal entries: {len(vibe_engine.quality_journal)}")

        if vibe_engine.average_age == 25:
            logger.warning("  ⚠ average_age is still default (25) — detections may not be logging!")
            issues.append("Detections not updating average_age")
        else:
            logger.info(f"  ✓ Detections are logging (avg_age changed from 25 to {vibe_engine.average_age})")

        # Check quality journal
        for entry in vibe_engine.quality_journal:
            logger.info(f"    Journal entry: {entry}")

        return issues
    except Exception as e:
        logger.error(f"  FAILED: {e}", exc_info=True)
        return [f"Processing loop test failed: {e}"]

def main():
    logger.info("")
    logger.info("╔" + "═" * 58 + "╗")
    logger.info("║" + "  Vibe Alchemist V2 — Detection Flow Validator".ljust(58) + "║")
    logger.info("╚" + "═" * 58 + "╝")
    logger.info("")

    all_issues = []

    # Run all tests
    all_issues.extend(("ENV", test_env()))
    all_issues.extend(("PLAYER", test_music_player()))
    all_issues.extend(("ENGINE", test_vibe_engine()))
    all_issues.extend(("VAULT", test_face_vault()))
    all_issues.extend(("PIPELINE", test_vision_pipeline()))
    all_issues.extend(("PROCESSING", test_processing_loop()))

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 60)

    total_issues = sum(len(issues) for _, issues in all_issues)
    if total_issues == 0:
        logger.info("✅ ALL TESTS PASSED — Detection flow is working!")
    else:
        logger.warning(f"⚠ {total_issues} issue(s) found:")
        for name, issues in all_issues:
            for issue in issues:
                logger.warning(f"  [{name}] {issue}")

    return total_issues

if __name__ == "__main__":
    sys.exit(main())
