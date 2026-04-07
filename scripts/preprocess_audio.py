#!/usr/bin/env python3
"""
Run ONCE before starting server to scan all music files for LUFS.
Writes a .lufs sidecar JSON next to each audio file.
AudioEngine reads sidecar at load time to adjust volume.

Usage:
    python scripts/preprocess_audio.py

Requires: pip install pyloudnorm soundfile

The server will still START without these sidecars (plays at default volume).
"""
import os
import sys
import glob
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Resolve project root (parent of scripts/)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)

ROOT = os.getenv("ROOT_MUSIC_DIR", os.path.join(project_root, "OfflinePlayback"))
TARGET_LUFS = float(os.getenv("LUFS_TARGET", -14.0))

try:
    import pyloudnorm as pyln
    import soundfile as sf

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    logger.error(
        "pyloudnorm or soundfile not installed. "
        "Install: pip install pyloudnorm soundfile"
    )
    sys.exit(1)


def scan_file(path: str) -> float:
    """Returns measured integrated LUFS of audio file."""
    data, rate = sf.read(path)
    if data.ndim == 1:
        data = data[:, None]
    meter = pyln.Meter(rate)
    return meter.integrated_loudness(data)


def process_all():
    """Scan all audio files in ROOT_MUSIC_DIR and write .lufs sidecars."""
    if not os.path.isdir(ROOT):
        logger.warning(f"Music directory not found: {ROOT}")
        logger.info("Create OfflinePlayback/ with music files, then re-run.")
        return

    exts = ["*.mp3", "*.wav", "*.flac", "*.ogg", "*.m4a"]
    all_files = []
    for ext in exts:
        all_files.extend(glob.glob(os.path.join(ROOT, "**", ext), recursive=True))

    if not all_files:
        logger.warning(f"No audio files found in {ROOT}")
        logger.info("Add music files to OfflinePlayback/ subfolders, then re-run.")
        return

    logger.info(f"Found {len(all_files)} audio files in {ROOT}")
    processed = 0
    skipped = 0
    errors = 0

    for path in all_files:
        sidecar = path + ".lufs"
        if os.path.exists(sidecar):
            skipped += 1
            continue

        try:
            lufs = scan_file(path)
            gain_db = TARGET_LUFS - lufs
            with open(sidecar, "w") as f:
                json.dump(
                    {"lufs": lufs, "gain_db": round(gain_db, 2), "target": TARGET_LUFS},
                    f,
                    indent=2,
                )
            logger.info(
                f"  [{processed + 1}/{len(all_files)}] "
                f"{os.path.basename(path)}: {lufs:.1f} LUFS → gain {gain_db:+.1f} dB"
            )
            processed += 1
        except Exception as e:
            logger.warning(f"  SKIP {os.path.basename(path)}: {e}")
            errors += 1

    logger.info("")
    logger.info("=" * 50)
    logger.info(f"  Processed: {processed}")
    logger.info(f"  Skipped (already done): {skipped}")
    logger.info(f"  Errors: {errors}")
    logger.info("=" * 50)
    logger.info("LUFS scan complete. Start server: python main.py")


if __name__ == "__main__":
    process_all()
