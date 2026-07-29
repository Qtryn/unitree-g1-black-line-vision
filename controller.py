from __future__ import annotations

from typing import Any

import numpy as np

from models import ControlResult, VisionResult


class LineController:
    def __init__(
        self,
        config: dict[str, Any],
    ) -> None:
        self.control = config["control"]
        self.missing_updates = 0
        self.line_was_followed = False
        self.last_good_confidence = 0.0

    def reset(self) -> None:
        self.missing_updates = 0
        self.line_was_followed = False
        self.last_good_confidence = 0.0

    def update(
        self,
        result: VisionResult,
        stale_updates: int,
    ) -> ControlResult:
        if (
            result.angle_deg is not None
            and result.lateral_error_norm is not None
            and result.confidence > 0.05
        ):
            if result.detected:
                self.missing_updates = 0
            else:
                self.missing_updates += 1

            self.last_good_confidence = max(
                self.last_good_confidence * 0.94,
                result.confidence,
            )

            output = self._compute(
                result.angle_deg,
                result.lateral_error_norm,
                result.confidence,
                stale_updates,
                result.detected,
            )

            if output.state in {
                "FORWARD",
                "ALIGN_AND_FORWARD",
            }:
                self.line_was_followed = True

            return output

        self.missing_updates += 1

        line_end = (
            self.line_was_followed
            and self.missing_updates
            >= int(self.control["line_end_missing_updates"])
            and self.last_good_confidence
            >= float(
                self.control[
                    "line_end_min_previous_confidence"
                ]
            )
        )

        return ControlResult(
            state="LINE_END" if line_end else "LINE_LOST",
            line_detected=False,
            line_end_detected=line_end,
            yaw_command=0.0,
            lateral_command=0.0,
            forward_command=0.0,
            angle_deg=None,
            lateral_error_norm=None,
            confidence=0.0,
            stale_updates=stale_updates,
        )

    def _compute(
        self,
        angle_deg: float,
        lateral_error_norm: float,
        confidence: float,
        stale_updates: int,
        freshly_detected: bool,
    ) -> ControlResult:
        angle_deadband = float(
            self.control["angle_deadband_deg"]
        )
        lateral_deadband = float(
            self.control["lateral_deadband_norm"]
        )

        yaw = float(
            np.clip(
                -float(self.control["yaw_kp"]) * angle_deg,
                -float(self.control["max_yaw_command"]),
                float(self.control["max_yaw_command"]),
            )
        )
        lateral = float(
            np.clip(
                -float(self.control["lateral_kp"])
                * lateral_error_norm,
                -float(self.control["max_lateral_command"]),
                float(self.control["max_lateral_command"]),
            )
        )

        angle_ok = abs(angle_deg) <= angle_deadband
        lateral_ok = abs(lateral_error_norm) <= lateral_deadband

        if angle_ok:
            yaw = 0.0
        if lateral_ok:
            lateral = 0.0

        if angle_ok and lateral_ok:
            state = "FORWARD"
            forward = float(self.control["forward_speed"])
        elif not angle_ok:
            state = "TURN_LEFT" if yaw > 0 else "TURN_RIGHT"
            forward = 0.0
        elif not lateral_ok:
            state = (
                "MOVE_LEFT"
                if lateral > 0
                else "MOVE_RIGHT"
            )
            forward = 0.0
        else:
            state = "ALIGN_AND_FORWARD"
            forward = float(
                self.control["align_forward_speed"]
            )

        if not freshly_detected:
            state = "HOLD_" + state
            forward *= 0.30
            yaw *= 0.55
            lateral *= 0.55

        return ControlResult(
            state=state,
            line_detected=freshly_detected,
            line_end_detected=False,
            yaw_command=yaw,
            lateral_command=lateral,
            forward_command=forward,
            angle_deg=float(angle_deg),
            lateral_error_norm=float(lateral_error_norm),
            confidence=float(confidence),
            stale_updates=stale_updates,
        )
