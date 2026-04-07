"""
Fuzzy Inference System for vibe selection.
Maps age + emotional energy + crowd size → music folder name.
Uses scikit-fuzzy (skfuzzy) for Mamdani-style fuzzy reasoning.

Unlike hard thresholds (age 17.9 = teen music, 18.1 = adult music),
fuzzy logic allows smooth transitions between vibe categories.

Input:  age (0-80), energy (0-1), crowd_size (1-10)
Output: vibe folder name (str) → maps to OfflinePlayback subfolder

Vibe folders:
    chill_ambient, lofi_jazz, pop_indie,
    hiphop_edm, classical_ambient, party_upbeat
"""
import os
import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    import skfuzzy as fuzz
    import skfuzzy.control as ctrl

    _SKFUZZY_AVAILABLE = True
except ImportError:
    _SKFUZZY_AVAILABLE = False
    logger.warning(
        "scikit-fuzzy not installed — fuzzy vibe disabled, using defaults. "
        "Install: pip install scikit-fuzzy"
    )


class FuzzyVibeEngine:
    """
    Fuzzy logic engine that maps demographic + emotional state to a music vibe.
    Gracefully degrades to "default" folder if skfuzzy is unavailable.
    """

    # Maps vibe index to folder name
    VIBE_FOLDERS = [
        "chill_ambient",
        "lofi_jazz",
        "pop_indie",
        "hiphop_edm",
        "classical_ambient",
        "party_upbeat",
    ]

    def __init__(self):
        self._sim = None
        if _SKFUZZY_AVAILABLE:
            self._build_system()

    def _build_system(self):
        """Construct the fuzzy inference system (Mamdani)."""
        try:
            # ── Input universes ──
            age = ctrl.Antecedent(np.arange(0, 81, 1), "age")
            energy = ctrl.Antecedent(np.arange(0, 1.01, 0.01), "energy")
            crowd = ctrl.Antecedent(np.arange(1, 11, 1), "crowd")

            # ── Output: vibe index (0-5 maps to folder names) ──
            vibe = ctrl.Consequent(np.arange(0, 6, 1), "vibe")

            # ── Age membership functions (triangular, overlapping) ──
            age["teen"] = fuzz.trimf(age.universe, [0, 10, 22])
            age["young_adult"] = fuzz.trimf(age.universe, [18, 28, 40])
            age["adult"] = fuzz.trimf(age.universe, [35, 45, 60])
            age["senior"] = fuzz.trimf(age.universe, [55, 70, 80])

            # ── Energy membership functions ──
            energy["low"] = fuzz.trimf(energy.universe, [0, 0, 0.45])
            energy["medium"] = fuzz.trimf(energy.universe, [0.3, 0.5, 0.7])
            energy["high"] = fuzz.trimf(energy.universe, [0.55, 1, 1])

            # ── Crowd membership functions ──
            crowd["solo"] = fuzz.trimf(crowd.universe, [1, 1, 3])
            crowd["small_group"] = fuzz.trimf(crowd.universe, [2, 4, 6])
            crowd["large"] = fuzz.trimf(crowd.universe, [5, 8, 10])

            # ── Vibe output membership functions ──
            vibe["chill"] = fuzz.trimf(vibe.universe, [0, 0, 1])
            vibe["lofi_jazz"] = fuzz.trimf(vibe.universe, [0, 1, 2])
            vibe["pop_indie"] = fuzz.trimf(vibe.universe, [1, 2, 3])
            vibe["hiphop_edm"] = fuzz.trimf(vibe.universe, [2, 3, 4])
            vibe["classical"] = fuzz.trimf(vibe.universe, [3, 4, 5])
            vibe["party"] = fuzz.trimf(vibe.universe, [4, 5, 5])

            # ── Fuzzy rules ──
            rules = [
                ctrl.Rule(age["teen"] & energy["high"], vibe["hiphop_edm"]),
                ctrl.Rule(age["teen"] & energy["medium"], vibe["pop_indie"]),
                ctrl.Rule(age["teen"] & energy["low"], vibe["chill"]),
                ctrl.Rule(age["young_adult"] & energy["high"], vibe["pop_indie"]),
                ctrl.Rule(age["young_adult"] & energy["medium"], vibe["pop_indie"]),
                ctrl.Rule(age["young_adult"] & energy["low"], vibe["lofi_jazz"]),
                ctrl.Rule(age["adult"] & energy["high"], vibe["pop_indie"]),
                ctrl.Rule(age["adult"] & energy["medium"], vibe["lofi_jazz"]),
                ctrl.Rule(age["adult"] & energy["low"], vibe["lofi_jazz"]),
                ctrl.Rule(age["senior"] & energy["low"], vibe["classical"]),
                ctrl.Rule(age["senior"] & energy["medium"], vibe["classical"]),
                ctrl.Rule(age["senior"] & energy["high"], vibe["pop_indie"]),
                ctrl.Rule(crowd["large"] & energy["high"], vibe["party"]),
                ctrl.Rule(crowd["large"] & energy["medium"], vibe["pop_indie"]),
                ctrl.Rule(crowd["small_group"] & energy["high"], vibe["party"]),
                ctrl.Rule(crowd["solo"] & energy["low"], vibe["chill"]),
                ctrl.Rule(crowd["solo"] & energy["medium"], vibe["lofi_jazz"]),
            ]

            vibe_ctrl = ctrl.ControlSystem(rules)
            self._sim = ctrl.ControlSystemSimulation(vibe_ctrl)
            logger.info("FuzzyVibeEngine initialized (scikit-fuzzy)")

        except Exception as e:
            logger.error(f"FuzzyVibeEngine build failed: {e}")
            self._sim = None

    def get_vibe_folder(self, age: float, energy: float, crowd_size: int) -> str:
        """
        Compute the best music folder for the given demographic state.
        :param age: Estimated age in years (0-80).
        :param energy: Emotional energy (0-1), from EmotionEngine.
        :param crowd_size: Number of detected persons (1-10).
        :returns: Subfolder name within OfflinePlayback.
        """
        if self._sim is None:
            return "default"

        try:
            self._sim.input["age"] = max(0, min(80, age))
            self._sim.input["energy"] = max(0, min(1, energy))
            self._sim.input["crowd"] = max(1, min(10, crowd_size))
            self._sim.compute()

            idx = int(round(self._sim.output["vibe"]))
            idx = max(0, min(5, idx))
            folder = self.VIBE_FOLDERS[idx]

            # Verify folder exists; fall back to default if not
            root = os.getenv("ROOT_MUSIC_DIR", "./OfflinePlayback")
            if os.path.isdir(os.path.join(root, folder)):
                return folder
            return "default"

        except Exception as e:
            logger.error(f"FuzzyVibeEngine compute error: {e}")
            return "default"
