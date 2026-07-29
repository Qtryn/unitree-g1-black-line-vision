from __future__ import annotations

from typing import Any
from copy import copy

import numpy as np

from models import VisionResult


class EMA:
    def __init__(self, alpha: float) -> None:
        self.alpha = float(alpha)
        self.value: float | None = None

    def update(self, value: float) -> float:
        if self.value is None:
            self.value = float(value)
        else:
            self.value = (
                self.alpha * float(value)
                + (1.0 - self.alpha) * self.value
            )
        return self.value

    def reset(self) -> None:
        self.value = None


class StableLineTracker:
    def __init__(
        self,
        config: dict[str, Any],
        profile_name: str,
    ) -> None:
        self.config = config
        self.track_cfg = config["tracking"]
        self.profile_name = profile_name
        self.profile = config["profiles"][profile_name]

        self.center = EMA(self.track_cfg["center_alpha"])
        self.angle = EMA(self.track_cfg["angle_alpha"])
        self.confidence = EMA(
            self.track_cfg["confidence_alpha"]
        )

        self.stale_updates = 0
        self.last_result: VisionResult | None = None

    def set_profile(self, profile_name: str) -> None:
        self.profile_name = profile_name
        self.profile = self.config["profiles"][profile_name]

    def reset(self) -> None:
        self.center.reset()
        self.angle.reset()
        self.confidence.reset()
        self.stale_updates = 0
        self.last_result = None

    def update(
        self,
        result: VisionResult,
    ) -> VisionResult:
        if (
            result.detected
            and result.angle_deg is not None
            and result.lateral_error_norm is not None
        ):
            max_center_jump = float(
                self.track_cfg["max_center_jump_norm"]
            )
            max_angle_jump = float(
                self.track_cfg["max_angle_jump_deg"]
            )

            if self.last_result is not None:
                previous_center = (
                    self.last_result.lateral_error_norm
                )
                previous_angle = self.last_result.angle_deg

                center_jump = (
                    abs(
                        result.lateral_error_norm
                        - previous_center
                    )
                    if previous_center is not None
                    else 0.0
                )
                angle_jump = (
                    abs(result.angle_deg - previous_angle)
                    if previous_angle is not None
                    else 0.0
                )

                if (
                    center_jump > max_center_jump
                    and angle_jump > max_angle_jump
                    and result.confidence < 0.72
                ):
                    return self._hold(result)

            result.lateral_error_norm = self.center.update(
                result.lateral_error_norm
            )
            result.angle_deg = self.angle.update(
                result.angle_deg
            )
            result.confidence = self.confidence.update(
                result.confidence
            )

            self.stale_updates = 0
            self.last_result = result
            return result

        return self._hold(result)

    def _hold(
        self,
        current: VisionResult,
    ) -> VisionResult:
        self.stale_updates += 1
        hold_updates = int(self.profile["hold_updates"])

        if (
            self.last_result is not None
            and self.stale_updates <= hold_updates
        ):
            held = copy(self.last_result)
            held.detected = False
            held.confidence = float(held.confidence * 0.88)
            return held

        if self.stale_updates >= int(
            self.track_cfg["reset_after_updates"]
        ):
            self.reset()

        return current
