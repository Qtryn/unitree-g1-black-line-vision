from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass
class Candidate:
    contour: np.ndarray
    mask: np.ndarray
    score: float
    center_x: float
    center_y: float
    area_ratio: float
    elongation: float
    solidity: float
    vertical_span_ratio: float
    bottom_proximity: float
    dark_contrast: float
    temporal_proximity: float


@dataclass
class VisionResult:
    detected: bool
    confidence: float
    angle_deg: float | None
    lateral_error_px: float | None
    lateral_error_norm: float | None
    center_x: float | None
    center_y: float | None
    visible_length_px: float
    forward_distance_cm: float | None

    roi_rect: tuple[int, int, int, int]
    view: np.ndarray
    gray: np.ndarray
    vote_mask: np.ndarray
    selected_mask: np.ndarray
    contour: np.ndarray | None
    candidates: list[Candidate]

    scan_points: np.ndarray | None
    inlier_mask: np.ndarray | None
    centerline_points: np.ndarray | None
    fitted_line_points: tuple[tuple[int, int], tuple[int, int]] | None


@dataclass
class ControlResult:
    state: str
    line_detected: bool
    line_end_detected: bool
    yaw_command: float
    lateral_command: float
    forward_command: float
    angle_deg: float | None
    lateral_error_norm: float | None
    confidence: float
    stale_updates: int
