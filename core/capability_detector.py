"""
VibeAlchemist2 V5 — Hardware Capability Detector
Runs once at startup. Benchmarks CPU speed, detects RAM + GPU.
Returns a Tier (1=LOW, 2=MEDIUM, 3=HIGH) that drives model selection.

TIER 1 (LOW):  RPi 4 / old CPU — 240p, motion-gated, minimal features
TIER 2 (MED):  RPi 5 / modern laptop — 480p, tiered inference, all features
TIER 3 (HIGH): GPU / powerful CPU — 720p, full resolution, all features

Auto-detected but overridable via FORCE_TIER=1|2|3 in .env.
"""
import os
import sys
import time
import platform
import logging

logger = logging.getLogger(__name__)

# Benchmark config
_BENCH_DURATION = 3.0   # seconds to run benchmark
_TIER1_THRESHOLD = 80   # ops/sec below this -> Tier 1
_TIER2_THRESHOLD = 200  # ops/sec below this -> Tier 2, above -> Tier 3


def _cpu_benchmark() -> float:
    """
    Simple integer math benchmark.
    Returns operations-per-second score (higher = faster CPU).
    """
    count = 0
    start = time.perf_counter()
    deadline = start + _BENCH_DURATION
    x = 1
    while time.perf_counter() < deadline:
        # Simulate float math similar to ONNX inference overhead
        x = (x * 1.0001 + 0.0001) % 1000.0
        count += 1
    elapsed = time.perf_counter() - start
    score = (count / elapsed) / 1_000_000  # normalize to M-ops/sec
    return round(score, 2)


def _get_available_ram_gb() -> float:
    """Returns available system RAM in GB."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except ImportError:
        # Fallback: read /proc/meminfo on Linux
        if sys.platform == "linux":
            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if "MemAvailable" in line:
                            kb = int(line.split()[1])
                            return kb / (1024 ** 2)
            except Exception:
                pass
        return 2.0  # assume 2GB if unknown


def _detect_gpu() -> str:
    """
    Returns 'cuda', 'mps', or 'none'.
    Checks without importing torch if possible (saves startup time).
    """
    # Check CUDA via onnxruntime providers (fast, no torch needed)
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        if "CUDAExecutionProvider" in providers:
            return "cuda"
        if "CoreMLExecutionProvider" in providers:
            return "mps"
    except ImportError:
        pass

    # Fallback: check nvidia-smi
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, timeout=3
        )
        if result.returncode == 0 and result.stdout.strip():
            return "cuda"
    except Exception:
        pass

    return "none"


def _select_tier(score: float, ram_gb: float, gpu: str) -> int:
    """Pure logic: given metrics -> return tier 1, 2, or 3."""
    # GPU always gets Tier 3 regardless of CPU
    if gpu in ("cuda", "mps") and ram_gb >= 2.0:
        return 3

    if score >= _TIER2_THRESHOLD and ram_gb >= 1.5:
        return 3
    elif score >= _TIER1_THRESHOLD and ram_gb >= 1.0:
        return 2
    else:
        return 1


class SystemProfile:
    """Holds the result of capability detection. Shared across all modules."""

    def __init__(self):
        self.tier: int = 2              # default until detect() runs
        self.cpu_score: float = 0.0
        self.ram_gb: float = 0.0
        self.gpu: str = "none"
        self.platform: str = sys.platform
        self.forced: bool = False
        self._detected: bool = False

    def detect(self):
        """
        Run benchmarks and set tier.
        Call once at startup BEFORE loading any models.
        """
        # Allow manual override via env
        force = os.getenv("FORCE_TIER", "").strip()
        if force in ("1", "2", "3"):
            self.tier = int(force)
            self.forced = True
            logger.info(f"SystemProfile: FORCE_TIER={self.tier} (manual override)")
            self._detected = True
            return

        logger.info("SystemProfile: Running hardware benchmark (~3s)...")
        self.gpu = _detect_gpu()
        self.ram_gb = round(_get_available_ram_gb(), 2)
        self.cpu_score = _cpu_benchmark()
        self.tier = _select_tier(self.cpu_score, self.ram_gb, self.gpu)
        self._detected = True

        logger.info(
            f"SystemProfile result: "
            f"CPU={self.cpu_score} Mop/s | "
            f"RAM={self.ram_gb:.1f}GB | "
            f"GPU={self.gpu} | "
            f"-> TIER {self.tier} ({self._tier_name()})"
        )

    def _tier_name(self) -> str:
        return {1: "LOW", 2: "MEDIUM", 3: "HIGH"}.get(self.tier, "UNKNOWN")

    def summary(self) -> dict:
        return {
            "tier": self.tier,
            "tier_name": self._tier_name(),
            "cpu_score": self.cpu_score,
            "ram_gb": self.ram_gb,
            "gpu": self.gpu,
            "platform": self.platform,
            "forced": self.forced,
        }


# Singleton — import this everywhere
PROFILE = SystemProfile()
