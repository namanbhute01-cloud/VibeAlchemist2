"""
Face Quality Scorer V4 — Advanced face quality assessment for accurate age estimation

Evaluates face quality across multiple dimensions:
1. Sharpness (Laplacian variance)
2. Brightness/contrast (histogram analysis)
3. Size (face pixel dimensions)
4. Frontalness (aspect ratio + symmetry)
5. Occlusion detection (edge density analysis)

Returns quality score 0.0-1.0 that weights age estimation confidence.
"""
import cv2
import numpy as np
import logging

logger = logging.getLogger("FaceQuality")


class FaceQualityScorer:
    """
    Advanced face quality assessment for age estimation gating.
    
    Usage:
        scorer = FaceQualityScorer()
        quality, details = scorer.assess(face_crop)
    """

    def __init__(self, min_face_size=15):  # Lowered from 30 for restaurant range
        self.min_face_size = min_face_size

        # Quality thresholds (VERY RELAXED for restaurant range)
        self.min_sharpness = 30       # Lowered from 50 for distant/blurry faces
        self.min_brightness = 20      # Lowered from 25 for dim restaurant lighting
        self.max_brightness = 245     # Raised from 240 for bright areas
        self.max_aspect_ratio = 3.0   # Raised from 2.5 for angled faces
        self.min_edge_density = 0.03  # Lowered from 0.05 for small faces

        # Quality score weights
        self.weights = {
            "sharpness": 0.30,
            "brightness": 0.20,
            "size": 0.25,
            "frontalness": 0.15,
            "feature_density": 0.10,
        }

    def assess(self, face_crop):
        """
        Assess face quality across multiple dimensions.
        
        Args:
            face_crop: Face image (BGR numpy array)
        
        Returns:
            (quality_score, details_dict)
            quality_score: 0.0-1.0 (higher = better for age estimation)
            details: Dict with per-dimension scores
        """
        if face_crop is None or face_crop.size == 0:
            return 0.0, {"error": "empty face crop"}

        h, w = face_crop.shape[:2]
        details = {}

        # 1. Sharpness (Laplacian variance)
        sharpness = self._assess_sharpness(face_crop)
        details["sharpness"] = sharpness

        # 2. Brightness/contrast
        brightness = self._assess_brightness(face_crop)
        details["brightness"] = brightness

        # 3. Size score
        size_score = self._assess_size(face_crop)
        details["size"] = size_score

        # 4. Frontalness (aspect ratio + symmetry)
        frontalness = self._assess_frontalness(face_crop)
        details["frontalness"] = frontalness

        # 5. Feature density (edge analysis)
        feature_density = self._assess_feature_density(face_crop)
        details["feature_density"] = feature_density

        # Weighted overall quality
        quality_score = sum(
            details[k] * self.weights[k]
            for k in self.weights
        )

        details["overall"] = quality_score
        details["is_good"] = quality_score >= 0.08 and sharpness >= self.min_sharpness  # Lowered from 0.15 for restaurant range

        return quality_score, details

    def _assess_sharpness(self, face_crop):
        """Assess image sharpness using Laplacian variance."""
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()

            # Normalize to 0-1 range (typical range: 0-500)
            score = min(1.0, lap_var / 300.0)
            return score
        except Exception:
            return 0.0

    def _assess_brightness(self, face_crop):
        """Assess brightness and contrast quality."""
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            mean_brightness = np.mean(gray)

            # Ideal range: 60-180 (well-lit but not overexposed)
            if self.min_brightness <= mean_brightness <= self.max_brightness:
                # Score based on distance from ideal center (120)
                distance = abs(mean_brightness - 120)
                score = max(0.0, 1.0 - distance / 120.0)
            else:
                score = 0.0

            return score
        except Exception:
            return 0.0

    def _assess_size(self, face_crop):
        """Assess face size adequacy for age estimation."""
        h, w = face_crop.shape[:2]
        min_dim = min(h, w)

        if min_dim < self.min_face_size:
            return 0.0

        # Ideal size: 80+ pixels (good for DEX/MiVOLO)
        # Score scales from 0 at min_size to 1.0 at 120px
        score = min(1.0, (min_dim - self.min_face_size) / 80.0)
        return max(0.0, score)

    def _assess_frontalness(self, face_crop):
        """
        Assess how frontal the face is using aspect ratio and symmetry.
        Frontal faces are much better for age estimation.
        """
        try:
            h, w = face_crop.shape[:2]
            aspect = max(w, h) / min(w, h) if min(w, h) > 0 else 10.0

            # Aspect ratio score (ideal = 1.0, acceptable up to 2.5)
            if aspect > self.max_aspect_ratio:
                aspect_score = 0.0
            else:
                aspect_score = max(0.0, 1.0 - (aspect - 1.0) / (self.max_aspect_ratio - 1.0))

            # Symmetry check (left-right mirror comparison)
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (64, 64))  # Normalize size
            mid = gray.shape[1] // 2
            left = gray[:, :mid]
            right = cv2.flip(gray[:, mid:], 1)

            # Normalize to same size if odd width
            min_w = min(left.shape[1], right.shape[1])
            left = left[:, :min_w]
            right = right[:, :min_w]

            # Correlation between left and right halves
            if left.std() > 0 and right.std() > 0:
                correlation = np.corrcoef(left.flatten(), right.flatten())[0, 1]
                symmetry_score = max(0.0, correlation)  # Correlation can be negative
            else:
                symmetry_score = 0.0

            # Combined frontalness (aspect more important than symmetry)
            return 0.7 * aspect_score + 0.3 * symmetry_score

        except Exception:
            return 0.0

    def _assess_feature_density(self, face_crop):
        """
        Assess facial feature density using edge detection.
        Higher edge density = more visible features = better age estimation.
        """
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)

            # Canny edge detection
            edges = cv2.Canny(gray, 50, 150)

            # Edge density = ratio of edge pixels to total pixels
            edge_pixels = np.count_nonzero(edges)
            total_pixels = edges.shape[0] * edges.shape[1]
            edge_density = edge_pixels / max(1, total_pixels)

            # Normalize to 0-1 (typical range: 0.02-0.30)
            score = min(1.0, edge_density / 0.15)

            return score
        except Exception:
            return 0.0

    def estimate_face_angle(self, face_crop):
        """
        Estimate approximate face yaw angle using symmetry analysis.
        Returns estimated angle in degrees (0 = frontal, positive = right turn).
        """
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (64, 64))
            mid = gray.shape[1] // 2

            left = gray[:, :mid]
            right = gray[:, mid:]

            # Compare brightness distribution
            left_mean = np.mean(left)
            right_mean = np.mean(right)

            # Shadow side is darker — indicates direction of turn
            diff = (left_mean - right_mean) / max(1, (left_mean + right_mean) / 2)

            # Rough angle estimate (empirical mapping)
            estimated_angle = diff * 45  # ±45 degrees range

            return estimated_angle
        except Exception:
            return 0.0

    def is_profile_view(self, face_crop, threshold=25.0):
        """
        Check if face is in profile view (turned significantly).
        Profile views have much lower age estimation accuracy.
        """
        angle = abs(self.estimate_face_angle(face_crop))
        is_profile = angle > threshold
        return is_profile, angle
