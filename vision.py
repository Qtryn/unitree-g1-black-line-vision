from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from models import Candidate, VisionResult


def odd(value: int, minimum: int = 3) -> int:
    value = max(minimum, int(value))
    return value if value % 2 else value + 1


def clamp01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


class BlackTapeVision:
    """Detect a dark tape line on a brighter floor.

    Color is used only through brightness-related channels. Hue is deliberately
    ignored because black has no stable hue. The default hybrid mode combines
    grayscale, adaptive threshold, HSV V/S, and black-hat responses.
    """

    MODES = {"gray_fixed", "adaptive", "hsv_black", "hybrid"}

    def __init__(
        self,
        config: dict[str, Any],
        profile_name: str = "balanced",
    ) -> None:
        self.config = config
        self.roi_cfg = config["roi"]
        self.profile_name = profile_name
        self.profile = config["profiles"][profile_name]
        self.detect_cfg = config["detection"]
        self.seg_cfg = config["segmentation"]
        self.line_cfg = config["line_model"]
        self.track_cfg = config["tracking"]
        self.calib_cfg = config["calibration"]

        self.previous_center_norm: float | None = None
        self.previous_angle_deg: float | None = None

        self.homography: np.ndarray | None = None
        self.pixels_per_cm_x = float(
            self.calib_cfg.get("pixels_per_cm_x", 0.0)
        )
        self.pixels_per_cm_y = float(
            self.calib_cfg.get("pixels_per_cm_y", 0.0)
        )
        self._load_homography()

    def set_profile(self, profile_name: str) -> None:
        if profile_name not in self.config["profiles"]:
            raise ValueError(f"Unknown profile: {profile_name}")
        self.profile_name = profile_name
        self.profile = self.config["profiles"][profile_name]

    def reset(self) -> None:
        self.previous_center_norm = None
        self.previous_angle_deg = None

    def _load_homography(self) -> None:
        if not bool(self.calib_cfg.get("birdseye_enabled", False)):
            return

        path = Path(str(self.calib_cfg["homography_file"]))
        if not path.exists():
            return

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        matrix = np.asarray(data.get("homography"), dtype=np.float64)
        if matrix.shape != (3, 3):
            return

        self.homography = matrix
        self.pixels_per_cm_x = float(
            data.get("pixels_per_cm_x", self.pixels_per_cm_x)
        )
        self.pixels_per_cm_y = float(
            data.get("pixels_per_cm_y", self.pixels_per_cm_y)
        )

    def _crop_roi(
        self,
        frame: np.ndarray,
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        height, width = frame.shape[:2]
        x1 = int(width * float(self.roi_cfg["left_ratio"]))
        x2 = int(width * float(self.roi_cfg["right_ratio"]))
        y1 = int(height * float(self.roi_cfg["top_ratio"]))
        y2 = int(height * float(self.roi_cfg["bottom_ratio"]))

        x1 = max(0, min(width - 1, x1))
        x2 = max(x1 + 1, min(width, x2))
        y1 = max(0, min(height - 1, y1))
        y2 = max(y1 + 1, min(height, y2))
        return frame[y1:y2, x1:x2].copy(), (x1, y1, x2, y2)

    def _processing_view(
        self,
        frame: np.ndarray,
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        roi, rect = self._crop_roi(frame)
        if self.homography is None:
            return roi, rect

        warped = cv2.warpPerspective(
            roi,
            self.homography,
            (
                int(self.calib_cfg["output_width"]),
                int(self.calib_cfg["output_height"]),
            ),
            flags=cv2.INTER_LINEAR,
        )
        return warped, rect

    def _preprocess(
        self,
        view: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        blur_size = odd(int(self.seg_cfg["blur_kernel"]))
        blurred = cv2.GaussianBlur(
            view,
            (blur_size, blur_size),
            0,
        )

        gray_raw = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(
            clipLimit=float(self.seg_cfg["clahe_clip_limit"]),
            tileGridSize=(
                int(self.seg_cfg["clahe_grid_size"]),
                int(self.seg_cfg["clahe_grid_size"]),
            ),
        )
        gray = clahe.apply(gray_raw)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        return gray, gray_raw, hsv

    def _threshold_masks(
        self,
        gray: np.ndarray,
        hsv: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        masks: dict[str, np.ndarray] = {}

        gray_max = int(self.detect_cfg["gray_max"])
        _, masks["gray_fixed"] = cv2.threshold(
            gray,
            gray_max,
            255,
            cv2.THRESH_BINARY_INV,
        )

        block = odd(int(self.seg_cfg["adaptive_block_size"]))
        adaptive_c = float(self.profile["adaptive_c"])
        masks["adaptive"] = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            block,
            adaptive_c,
        )

        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        hsv_mask = cv2.inRange(
            hsv,
            np.asarray([0, 0, 0], dtype=np.uint8),
            np.asarray(
                [
                    179,
                    int(self.detect_cfg["hsv_s_max"]),
                    int(self.detect_cfg["hsv_v_max"]),
                ],
                dtype=np.uint8,
            ),
        )
        masks["hsv_black"] = hsv_mask
        masks["hsv_s"] = saturation
        masks["hsv_v"] = value

        _, masks["otsu"] = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
        )

        blackhat_size = odd(int(self.seg_cfg["blackhat_kernel"]))
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (blackhat_size, blackhat_size),
        )
        blackhat_response = cv2.morphologyEx(
            gray,
            cv2.MORPH_BLACKHAT,
            kernel,
        )
        _, masks["blackhat"] = cv2.threshold(
            blackhat_response,
            int(self.seg_cfg["blackhat_threshold"]),
            255,
            cv2.THRESH_BINARY,
        )
        masks["blackhat_response"] = blackhat_response

        mode = str(self.detect_cfg["mode"]).lower()
        if mode not in self.MODES:
            mode = "hybrid"

        if mode != "hybrid":
            raw_mask = masks[mode].copy()
        else:
            enabled: list[np.ndarray] = []
            for name, key in (
                ("gray_fixed", "enable_gray_fixed"),
                ("adaptive", "enable_adaptive"),
                ("hsv_black", "enable_hsv_black"),
                ("otsu", "enable_otsu"),
                ("blackhat", "enable_blackhat"),
            ):
                if bool(self.detect_cfg.get(key, False)):
                    enabled.append(masks[name])

            if not enabled:
                enabled = [masks["gray_fixed"]]

            votes = np.zeros_like(gray, dtype=np.uint8)
            for mask in enabled:
                votes += (mask > 0).astype(np.uint8)

            required = max(
                1,
                min(int(self.detect_cfg["vote_required"]), len(enabled)),
            )
            raw_mask = np.where(
                votes >= required,
                255,
                0,
            ).astype(np.uint8)

            _, very_dark = cv2.threshold(
                value,
                int(self.detect_cfg["very_dark_max"]),
                255,
                cv2.THRESH_BINARY_INV,
            )
            raw_mask = cv2.bitwise_or(raw_mask, very_dark)
            masks["very_dark"] = very_dark

        masks["raw_selected"] = raw_mask.copy()
        clean = self._morphology(raw_mask)
        masks["clean"] = clean
        return clean, masks

    def _morphology(self, mask: np.ndarray) -> np.ndarray:
        close_size = odd(int(self.seg_cfg["close_kernel"]))
        open_size = odd(int(self.seg_cfg["open_kernel"]))

        close_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (close_size, close_size),
        )
        open_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (open_size, open_size),
        )

        result = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            close_kernel,
            iterations=int(self.seg_cfg["close_iterations"]),
        )
        result = cv2.morphologyEx(
            result,
            cv2.MORPH_OPEN,
            open_kernel,
            iterations=int(self.seg_cfg["open_iterations"]),
        )
        return result

    @staticmethod
    def _contour_stats(
        contour: np.ndarray,
        gray_raw: np.ndarray,
        image_area: float,
    ) -> dict[str, float]:
        area = float(abs(cv2.contourArea(contour)))
        x, y, width, height = cv2.boundingRect(contour)

        hull = cv2.convexHull(contour)
        hull_area = max(float(abs(cv2.contourArea(hull))), 1.0)
        solidity = area / hull_area

        rect = cv2.minAreaRect(contour)
        rect_w, rect_h = rect[1]
        shorter = max(min(rect_w, rect_h), 1.0)
        longer = max(rect_w, rect_h)
        elongation = longer / shorter

        component_mask = np.zeros_like(gray_raw, dtype=np.uint8)
        cv2.drawContours(
            component_mask,
            [contour],
            -1,
            255,
            thickness=-1,
        )
        inside = gray_raw[component_mask > 0]

        ring_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (17, 17),
        )
        dilated = cv2.dilate(component_mask, ring_kernel, iterations=1)
        ring = cv2.subtract(dilated, component_mask)
        outside = gray_raw[ring > 0]

        inside_mean = float(np.mean(inside)) if inside.size else 255.0
        outside_mean = (
            float(np.mean(outside)) if outside.size else inside_mean
        )
        dark_contrast = clamp01((outside_mean - inside_mean) / 120.0)

        moments = cv2.moments(contour)
        if abs(moments["m00"]) > 1e-6:
            center_x = moments["m10"] / moments["m00"]
            center_y = moments["m01"] / moments["m00"]
        else:
            center_x = x + width / 2.0
            center_y = y + height / 2.0

        return {
            "area_ratio": area / image_area,
            "solidity": solidity,
            "elongation": elongation,
            "center_x": center_x,
            "center_y": center_y,
            "vertical_span_ratio": height / gray_raw.shape[0],
            "horizontal_span_ratio": width / gray_raw.shape[1],
            "bottom_proximity": (y + height) / gray_raw.shape[0],
            "dark_contrast": dark_contrast,
        }

    def _temporal_proximity(self, center_x: float, width: int) -> float:
        if self.previous_center_norm is None:
            return 0.60

        current = center_x / max(width, 1)
        distance = abs(current - self.previous_center_norm)
        return clamp01(
            1.0
            - distance
            / max(float(self.track_cfg["max_center_jump_norm"]), 1e-6)
        )

    def _build_candidates(
        self,
        mask: np.ndarray,
        gray_raw: np.ndarray,
    ) -> list[Candidate]:
        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        height, width = gray_raw.shape
        image_area = float(height * width)
        min_area = float(self.profile["min_component_area_ratio"])
        max_area = float(self.seg_cfg["max_component_area_ratio"])
        min_elongation = float(self.profile["min_elongation"])
        min_solidity = float(self.seg_cfg["min_solidity"])
        min_vertical = float(self.seg_cfg["min_vertical_span_ratio"])
        min_bottom = float(self.seg_cfg["min_bottom_proximity"])
        min_contrast = float(self.seg_cfg["min_dark_contrast"])

        candidates: list[Candidate] = []
        for contour in contours:
            stats = self._contour_stats(contour, gray_raw, image_area)

            if not min_area <= stats["area_ratio"] <= max_area:
                continue
            if stats["solidity"] < min_solidity:
                continue
            if stats["elongation"] < min_elongation:
                continue
            major_span_ratio = max(
                stats["vertical_span_ratio"],
                stats["horizontal_span_ratio"],
            )
            horizontal_like = (
                stats["horizontal_span_ratio"]
                > stats["vertical_span_ratio"] * 1.25
            )

            # The old implementation required a large vertical span and
            # therefore rejected a perfectly horizontal tape line.  Use the
            # major-axis span instead.  Bottom proximity remains mandatory
            # for forward/vertical candidates, but is relaxed for a long
            # horizontal candidate because its purpose is to trigger a large
            # yaw correction.
            if major_span_ratio < min_vertical:
                continue
            if (not horizontal_like) and stats["bottom_proximity"] < min_bottom:
                continue
            if stats["dark_contrast"] < min_contrast:
                continue

            temporal = self._temporal_proximity(stats["center_x"], width)
            area_score = clamp01(stats["area_ratio"] / 0.08)
            elongation_score = clamp01(
                (stats["elongation"] - min_elongation) / 7.0
            )
            vertical_score = clamp01(major_span_ratio / 0.70)
            if horizontal_like:
                bottom_score = clamp01(stats["bottom_proximity"])
            else:
                bottom_score = clamp01(
                    (stats["bottom_proximity"] - min_bottom)
                    / max(1.0 - min_bottom, 1e-6)
                )

            score = (
                float(self.seg_cfg["weight_area"]) * area_score
                + float(self.seg_cfg["weight_elongation"]) * elongation_score
                + float(self.seg_cfg["weight_vertical_span"]) * vertical_score
                + float(self.seg_cfg["weight_bottom_proximity"]) * bottom_score
                + float(self.seg_cfg["weight_dark_contrast"])
                * stats["dark_contrast"]
                + float(self.seg_cfg["weight_temporal_proximity"])
                * temporal
            )

            component_mask = np.zeros_like(mask)
            cv2.drawContours(
                component_mask,
                [contour],
                -1,
                255,
                thickness=-1,
            )
            candidates.append(
                Candidate(
                    contour=contour,
                    mask=component_mask,
                    score=float(score),
                    center_x=float(stats["center_x"]),
                    center_y=float(stats["center_y"]),
                    area_ratio=float(stats["area_ratio"]),
                    elongation=float(stats["elongation"]),
                    solidity=float(stats["solidity"]),
                    vertical_span_ratio=float(stats["vertical_span_ratio"]),
                    bottom_proximity=float(stats["bottom_proximity"]),
                    dark_contrast=float(stats["dark_contrast"]),
                    temporal_proximity=float(temporal),
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[: int(self.seg_cfg["max_candidate_count"])]

    def _select_candidate(
        self,
        candidates: list[Candidate],
        shape: tuple[int, int],
    ) -> tuple[np.ndarray, np.ndarray | None]:
        if not candidates:
            return np.zeros(shape, dtype=np.uint8), None

        best = candidates[0]
        merged = best.mask.copy()
        image_width = shape[1]

        for candidate in candidates[1:]:
            distance = abs(candidate.center_x - best.center_x) / max(
                image_width,
                1,
            )
            if distance < 0.10 and candidate.score >= best.score * 0.72:
                merged = cv2.bitwise_or(merged, candidate.mask)

        contours, _ = cv2.findContours(
            merged,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        contour = max(contours, key=cv2.contourArea) if contours else best.contour
        return merged, contour

    def _sample_centers(
        self,
        mask: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
        height, width = mask.shape
        count = int(self.line_cfg["scanline_count"])
        band_height = max(3, int(self.line_cfg["scanline_band_height"]))
        expected_x = (
            self.previous_center_norm * width
            if self.previous_center_norm is not None
            else width / 2.0
        )

        y_positions = np.linspace(
            int(height * 0.08),
            int(height * 0.97),
            count,
        ).astype(int)

        points: list[tuple[float, float]] = []
        weights: list[float] = []
        widths: list[float] = []

        for y in y_positions:
            y1 = max(0, y - band_height // 2)
            y2 = min(height, y + band_height // 2 + 1)
            band = mask[y1:y2]
            column_counts = np.count_nonzero(band, axis=0).astype(np.float64)
            active_indices = np.flatnonzero(column_counts > 0)
            if active_indices.size == 0:
                continue

            split_positions = np.where(np.diff(active_indices) > 1)[0] + 1
            segments = np.split(active_indices, split_positions)
            best_segment: np.ndarray | None = None
            best_score = -1.0

            for segment in segments:
                if segment.size < 2:
                    continue
                segment_weights = column_counts[segment]
                center_x = float(
                    np.average(segment, weights=segment_weights)
                )
                proximity = clamp01(
                    1.0
                    - abs(center_x - expected_x)
                    / max(width * 0.36, 1.0)
                )
                width_score = min(segment.size / 45.0, 1.0)
                density_score = min(
                    float(np.sum(segment_weights))
                    / max(band_height * 40.0, 1.0),
                    1.0,
                )
                score = 0.45 * proximity + 0.30 * width_score + 0.25 * density_score
                if score > best_score:
                    best_score = score
                    best_segment = segment

            if best_segment is None:
                continue

            segment_weights = column_counts[best_segment]
            center_x = float(
                np.average(best_segment, weights=segment_weights)
            )
            normalized_y = y / max(height - 1, 1)
            near_weight = 1.0 + (
                float(self.line_cfg["near_weight"]) - 1.0
            ) * normalized_y

            points.append((center_x, float(y)))
            weights.append(near_weight)
            widths.append(float(best_segment[-1] - best_segment[0] + 1))

        if not points:
            return (
                np.empty((0, 2), dtype=np.float64),
                np.empty((0,), dtype=np.float64),
                np.empty((0,), dtype=np.float64),
                0.0,
                float("inf"),
            )

        width_array = np.asarray(widths, dtype=np.float64)
        continuity = len(points) / max(count, 1)
        width_cv = float(
            np.std(width_array) / max(np.mean(width_array), 1e-6)
        )
        return (
            np.asarray(points, dtype=np.float64),
            np.asarray(weights, dtype=np.float64),
            width_array,
            float(continuity),
            width_cv,
        )

    @staticmethod
    def _point_line_distance(
        points: np.ndarray,
        point_a: np.ndarray,
        point_b: np.ndarray,
    ) -> np.ndarray:
        direction = point_b - point_a
        norm = np.linalg.norm(direction)
        if norm < 1e-9:
            return np.full(len(points), np.inf)
        relative = points - point_a
        cross = direction[0] * relative[:, 1] - direction[1] * relative[:, 0]
        return np.abs(cross) / norm

    def _ransac(
        self,
        points: np.ndarray,
        weights: np.ndarray,
    ) -> tuple[np.ndarray | None, float]:
        min_points = int(self.line_cfg["min_scanline_points"])
        if len(points) < min_points:
            return None, 0.0

        rng = np.random.default_rng()
        best_inliers: np.ndarray | None = None
        best_score = -1.0
        threshold = float(self.line_cfg["ransac_distance_px"])

        for _ in range(int(self.line_cfg["ransac_iterations"])):
            indices = rng.choice(len(points), size=2, replace=False)
            distances = self._point_line_distance(
                points,
                points[indices[0]],
                points[indices[1]],
            )
            inliers = distances <= threshold
            if np.count_nonzero(inliers) < min_points:
                continue
            score = float(np.sum(weights[inliers]))
            if score > best_score:
                best_score = score
                best_inliers = inliers

        if best_inliers is None:
            return None, 0.0

        ratio = float(
            np.sum(weights[best_inliers]) / max(np.sum(weights), 1e-9)
        )
        if ratio < float(self.line_cfg["min_ransac_inlier_ratio"]):
            return None, ratio
        return best_inliers, ratio

    def _fit_centerline(
        self,
        points: np.ndarray,
        weights: np.ndarray,
        inliers: np.ndarray,
        height: int,
    ) -> tuple[
        np.ndarray,
        float,
        float,
        tuple[tuple[int, int], tuple[int, int]],
    ]:
        fit_points = points[inliers]
        fit_weights = weights[inliers]
        degree = 1
        if (
            bool(self.line_cfg["use_quadratic_fit"])
            and len(fit_points) >= int(self.line_cfg["quadratic_min_points"])
        ):
            degree = 2

        coefficients = np.polyfit(
            fit_points[:, 1],
            fit_points[:, 0],
            deg=degree,
            w=fit_weights,
        )
        lookahead_y = height * float(self.line_cfg["lookahead_y_ratio"])
        center_x = float(np.polyval(coefficients, lookahead_y))
        derivative = np.polyder(coefficients)
        dx_dy = float(np.polyval(derivative, lookahead_y))
        angle_deg = float(np.degrees(np.arctan(dx_dy)))

        sampled_y = np.linspace(0, height - 1, 90)
        sampled_x = np.polyval(coefficients, sampled_y)
        centerline = np.column_stack([sampled_x, sampled_y])
        endpoints = (
            (int(np.polyval(coefficients, height - 1)), height - 1),
            (int(np.polyval(coefficients, 0)), 0),
        )
        return centerline, center_x, angle_deg, endpoints

    def _fit_contour_pca(
        self,
        contour: np.ndarray,
        shape: tuple[int, int],
    ) -> tuple[
        np.ndarray,
        float,
        float,
        float,
        tuple[tuple[int, int], tuple[int, int]],
    ] | None:
        """Fit an orientation-independent centerline from contour pixels.

        This fallback is essential for a horizontal tape line.  Horizontal
        lines intersect only a few horizontal scan bands, so the normal
        scanline/RANSAC model may not have enough points.
        """
        if contour is None or len(contour) < 5:
            return None

        points = contour.reshape(-1, 2).astype(np.float64)
        center = np.mean(points, axis=0)
        centered = points - center
        covariance = centered.T @ centered / max(len(points), 1)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        direction = eigenvectors[:, int(np.argmax(eigenvalues))]

        # Normalize direction sign for stable temporal behavior.
        if direction[1] > 0 or (abs(direction[1]) < 1e-8 and direction[0] < 0):
            direction = -direction

        dx, dy = float(direction[0]), float(direction[1])
        angle_deg = float(np.degrees(np.arctan2(dx, -dy)))
        # Equivalent undirected lines must map into [-90, 90].
        if angle_deg > 90.0:
            angle_deg -= 180.0
        elif angle_deg < -90.0:
            angle_deg += 180.0

        height, width = shape
        projection = centered @ direction
        low = float(np.percentile(projection, 2.0))
        high = float(np.percentile(projection, 98.0))
        sampled = np.linspace(low, high, 90)
        centerline = center[None, :] + sampled[:, None] * direction[None, :]

        point_a = center + low * direction
        point_b = center + high * direction
        endpoints = (
            (
                int(np.clip(point_a[0], 0, width - 1)),
                int(np.clip(point_a[1], 0, height - 1)),
            ),
            (
                int(np.clip(point_b[0], 0, width - 1)),
                int(np.clip(point_b[1], 0, height - 1)),
            ),
        )
        return (
            centerline,
            float(center[0]),
            float(center[1]),
            angle_deg,
            endpoints,
        )

    def _forward_distance_cm(self, mask: np.ndarray) -> float | None:
        if self.pixels_per_cm_y <= 0:
            return None
        rows = np.flatnonzero(np.any(mask > 0, axis=1))
        if rows.size == 0:
            return None
        return float(rows[-1] - rows[0]) / self.pixels_per_cm_y

    def _empty_result(
        self,
        roi_rect: tuple[int, int, int, int],
        view: np.ndarray,
        gray: np.ndarray,
        clean_mask: np.ndarray,
        selected_mask: np.ndarray,
        contour: np.ndarray | None,
        candidates: list[Candidate],
        points: np.ndarray | None = None,
        inliers: np.ndarray | None = None,
    ) -> VisionResult:
        return VisionResult(
            detected=False,
            confidence=0.0,
            angle_deg=None,
            lateral_error_px=None,
            lateral_error_norm=None,
            center_x=None,
            center_y=None,
            visible_length_px=0.0,
            forward_distance_cm=None,
            roi_rect=roi_rect,
            view=view,
            gray=gray,
            vote_mask=clean_mask,
            selected_mask=selected_mask,
            contour=contour,
            candidates=candidates,
            scan_points=points,
            inlier_mask=inliers,
            centerline_points=None,
            fitted_line_points=None,
        )

    def detect(
        self,
        frame: np.ndarray,
    ) -> tuple[VisionResult, dict[str, np.ndarray]]:
        view, roi_rect = self._processing_view(frame)
        gray, gray_raw, hsv = self._preprocess(view)
        clean_mask, masks = self._threshold_masks(gray, hsv)
        masks["gray"] = gray
        masks["gray_raw"] = gray_raw

        candidates = self._build_candidates(clean_mask, gray_raw)
        selected_mask, contour = self._select_candidate(
            candidates,
            gray.shape,
        )
        masks["selected"] = selected_mask

        points, weights, widths, continuity, width_cv = self._sample_centers(
            selected_mask
        )
        masks["continuity_score"] = np.full_like(
            gray,
            int(np.clip(continuity, 0.0, 1.0) * 255),
        )

        use_scanline_model = (
            continuity >= float(self.line_cfg["min_continuity_ratio"])
            and width_cv <= float(self.line_cfg["max_width_cv"])
        )

        inliers: np.ndarray | None = None
        inlier_ratio = 0.0
        center_y: float

        if use_scanline_model:
            inliers, inlier_ratio = self._ransac(points, weights)

        if inliers is not None:
            centerline, center_x, angle_deg, endpoints = self._fit_centerline(
                points,
                weights,
                inliers,
                gray.shape[0],
            )
            center_y = float(
                gray.shape[0] * float(self.line_cfg["lookahead_y_ratio"])
            )
        else:
            pca_fit = self._fit_contour_pca(contour, gray.shape)
            if pca_fit is None:
                return (
                    self._empty_result(
                        roi_rect,
                        view,
                        gray,
                        clean_mask,
                        selected_mask,
                        contour,
                        candidates,
                        points if len(points) else None,
                    ),
                    masks,
                )
            centerline, center_x, center_y, angle_deg, endpoints = pca_fit
            # PCA confidence derives from the candidate geometry when the
            # scanline model is unavailable (especially near +/-90 degrees).
            inlier_ratio = candidates[0].score if candidates else 0.0

        if abs(angle_deg) > float(self.line_cfg["max_abs_angle_deg"]):
            return (
                self._empty_result(
                    roi_rect,
                    view,
                    gray,
                    clean_mask,
                    selected_mask,
                    contour,
                    candidates,
                    points if len(points) else None,
                    inliers,
                ),
                masks,
            )

        image_center_x = gray.shape[1] / 2.0
        lateral_error_px = center_x - image_center_x
        lateral_error_norm = lateral_error_px / max(image_center_x, 1.0)

        candidate_score = candidates[0].score if candidates else 0.0
        point_coverage = min(
            len(points) / max(int(self.line_cfg["scanline_count"]), 1),
            1.0,
        )
        width_score = clamp01(
            1.0 - width_cv / max(float(self.line_cfg["max_width_cv"]), 1e-6)
        )
        confidence = clamp01(
            0.32 * inlier_ratio
            + 0.24 * candidate_score
            + 0.20 * point_coverage
            + 0.14 * continuity
            + 0.10 * width_score
        )

        visible_length_px = 0.0
        if contour is not None:
            rect = cv2.minAreaRect(contour)
            visible_length_px = float(max(rect[1]))

        self.previous_center_norm = center_x / max(gray.shape[1], 1)
        self.previous_angle_deg = angle_deg

        result = VisionResult(
            detected=True,
            confidence=confidence,
            angle_deg=angle_deg,
            lateral_error_px=float(lateral_error_px),
            lateral_error_norm=float(lateral_error_norm),
            center_x=float(center_x),
            center_y=float(center_y),
            visible_length_px=visible_length_px,
            forward_distance_cm=self._forward_distance_cm(selected_mask),
            roi_rect=roi_rect,
            view=view,
            gray=gray,
            vote_mask=clean_mask,
            selected_mask=selected_mask,
            contour=contour,
            candidates=candidates,
            scan_points=points,
            inlier_mask=inliers,
            centerline_points=centerline,
            fitted_line_points=endpoints,
        )
        return result, masks
