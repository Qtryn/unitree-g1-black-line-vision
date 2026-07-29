from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from models import ControlResult, VisionResult


STATE_COLORS = {
    "FORWARD": (60, 205, 80),
    "ALIGN_AND_FORWARD": (30, 190, 220),
    "TURN_LEFT": (30, 145, 255),
    "TURN_RIGHT": (30, 145, 255),
    "MOVE_LEFT": (200, 130, 40),
    "MOVE_RIGHT": (200, 130, 40),
    "LINE_LOST": (55, 55, 225),
    "LINE_END": (170, 70, 210),
}


def rounded_rect(
    image: np.ndarray,
    top_left: tuple[int, int],
    bottom_right: tuple[int, int],
    color: tuple[int, int, int],
    radius: int = 18,
    thickness: int = -1,
) -> None:
    x1, y1 = top_left
    x2, y2 = bottom_right

    if thickness != -1:
        cv2.rectangle(
            image,
            (x1 + radius, y1),
            (x2 - radius, y2),
            color,
            thickness,
        )
        cv2.rectangle(
            image,
            (x1, y1 + radius),
            (x2, y2 - radius),
            color,
            thickness,
        )
        return

    cv2.rectangle(
        image,
        (x1 + radius, y1),
        (x2 - radius, y2),
        color,
        -1,
    )
    cv2.rectangle(
        image,
        (x1, y1 + radius),
        (x2, y2 - radius),
        color,
        -1,
    )
    cv2.circle(
        image,
        (x1 + radius, y1 + radius),
        radius,
        color,
        -1,
    )
    cv2.circle(
        image,
        (x2 - radius, y1 + radius),
        radius,
        color,
        -1,
    )
    cv2.circle(
        image,
        (x1 + radius, y2 - radius),
        radius,
        color,
        -1,
    )
    cv2.circle(
        image,
        (x2 - radius, y2 - radius),
        radius,
        color,
        -1,
    )


def put_text(
    image: np.ndarray,
    text: str,
    position: tuple[int, int],
    scale: float,
    color: tuple[int, int, int],
    thickness: int = 1,
) -> None:
    cv2.putText(
        image,
        text,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def resize_letterbox(
    image: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, float, int, int]:
    source_h, source_w = image.shape[:2]
    scale = min(
        width / max(source_w, 1),
        height / max(source_h, 1),
    )
    new_w = max(1, int(source_w * scale))
    new_h = max(1, int(source_h * scale))

    resized = cv2.resize(
        image,
        (new_w, new_h),
        interpolation=cv2.INTER_AREA,
    )
    canvas = np.zeros(
        (height, width, 3),
        dtype=np.uint8,
    )
    offset_x = (width - new_w) // 2
    offset_y = (height - new_h) // 2
    canvas[
        offset_y:offset_y + new_h,
        offset_x:offset_x + new_w,
    ] = resized
    return canvas, scale, offset_x, offset_y


def map_view_point_to_frame(
    point: tuple[float, float],
    result: VisionResult,
) -> tuple[int, int]:
    x1, y1, x2, y2 = result.roi_rect
    view_h, view_w = result.view.shape[:2]

    return (
        int(x1 + point[0] * (x2 - x1) / max(view_w, 1)),
        int(y1 + point[1] * (y2 - y1) / max(view_h, 1)),
    )


def draw_scene_overlay(
    frame: np.ndarray,
    result: VisionResult,
    config: dict[str, Any],
) -> np.ndarray:
    output = frame.copy()
    display = config["display"]

    x1, y1, x2, y2 = result.roi_rect
    cv2.rectangle(
        output,
        (x1, y1),
        (x2, y2),
        (255, 180, 40),
        2,
    )

    if bool(display["show_mask_overlay"]):
        target = output[y1:y2, x1:x2]
        mask = cv2.resize(
            result.selected_mask,
            (target.shape[1], target.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
        overlay = target.copy()
        overlay[mask > 0] = (0, 215, 255)
        output[y1:y2, x1:x2] = cv2.addWeighted(
            target,
            1.0 - float(display["mask_alpha"]),
            overlay,
            float(display["mask_alpha"]),
            0.0,
        )

    frame_center_x = (x1 + x2) // 2
    cv2.line(
        output,
        (frame_center_x, y1),
        (frame_center_x, y2),
        (255, 255, 40),
        2,
        cv2.LINE_AA,
    )

    if (
        result.centerline_points is not None
        and bool(display["show_debug_points"])
    ):
        mapped = [
            map_view_point_to_frame(
                (float(point[0]), float(point[1])),
                result,
            )
            for point in result.centerline_points
        ]
        mapped_array = np.asarray(
            mapped,
            dtype=np.int32,
        ).reshape((-1, 1, 2))

        cv2.polylines(
            output,
            [mapped_array],
            False,
            (40, 255, 40),
            int(display["line_thickness"]),
            cv2.LINE_AA,
        )

    if (
        result.scan_points is not None
        and bool(display["show_debug_points"])
    ):
        for index, point in enumerate(result.scan_points):
            mapped = map_view_point_to_frame(
                (float(point[0]), float(point[1])),
                result,
            )
            inlier = (
                result.inlier_mask is not None
                and index < len(result.inlier_mask)
                and bool(result.inlier_mask[index])
            )
            cv2.circle(
                output,
                mapped,
                int(display["point_radius"]),
                (0, 255, 255) if inlier else (90, 90, 255),
                -1,
                cv2.LINE_AA,
            )

    if (
        result.center_x is not None
        and result.center_y is not None
    ):
        control_point = map_view_point_to_frame(
            (result.center_x, result.center_y),
            result,
        )
        cv2.circle(
            output,
            control_point,
            10,
            (30, 30, 255),
            -1,
            cv2.LINE_AA,
        )
        cv2.line(
            output,
            (frame_center_x, control_point[1]),
            control_point,
            (255, 80, 255),
            4,
            cv2.LINE_AA,
        )

    return output


def draw_progress_bar(
    panel: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
    value: float,
    fill_color: tuple[int, int, int],
    label: str,
) -> None:
    value = float(np.clip(value, 0.0, 1.0))

    rounded_rect(
        panel,
        (x, y),
        (x + width, y + height),
        (52, 58, 68),
        radius=height // 2,
    )
    fill_width = int(width * value)

    if fill_width > height:
        rounded_rect(
            panel,
            (x, y),
            (x + fill_width, y + height),
            fill_color,
            radius=height // 2,
        )

    put_text(
        panel,
        label,
        (x, y - 8),
        0.50,
        (190, 198, 210),
        1,
    )


def draw_lateral_gauge(
    panel: np.ndarray,
    x: int,
    y: int,
    width: int,
    value: float | None,
) -> None:
    put_text(
        panel,
        "LATERAL ERROR",
        (x, y - 12),
        0.50,
        (190, 198, 210),
        1,
    )
    cv2.line(
        panel,
        (x, y),
        (x + width, y),
        (75, 82, 94),
        8,
        cv2.LINE_AA,
    )

    center = x + width // 2
    cv2.line(
        panel,
        (center, y - 12),
        (center, y + 12),
        (230, 235, 240),
        2,
    )

    if value is None:
        return

    marker = int(
        center + np.clip(value, -1.0, 1.0) * width / 2
    )
    cv2.circle(
        panel,
        (marker, y),
        10,
        (50, 210, 255),
        -1,
        cv2.LINE_AA,
    )


def draw_angle_gauge(
    panel: np.ndarray,
    center: tuple[int, int],
    radius: int,
    angle_deg: float | None,
) -> None:
    cx, cy = center
    cv2.ellipse(
        panel,
        center,
        (radius, radius),
        0,
        200,
        340,
        (75, 82, 94),
        4,
        cv2.LINE_AA,
    )
    cv2.line(
        panel,
        (cx, cy),
        (cx, cy - radius + 8),
        (110, 118, 130),
        2,
        cv2.LINE_AA,
    )

    if angle_deg is None:
        return

    display_angle = float(np.clip(angle_deg, -70.0, 70.0))
    radians = np.deg2rad(display_angle - 90.0)
    endpoint = (
        int(cx + (radius - 12) * np.cos(radians)),
        int(cy + (radius - 12) * np.sin(radians)),
    )
    cv2.line(
        panel,
        (cx, cy),
        endpoint,
        (40, 220, 255),
        5,
        cv2.LINE_AA,
    )
    cv2.circle(
        panel,
        (cx, cy),
        7,
        (235, 240, 245),
        -1,
    )


def compose_dashboard(
    frame: np.ndarray,
    result: VisionResult,
    control: ControlResult,
    threshold_masks: dict[str, np.ndarray],
    config: dict[str, Any],
    profile_name: str,
    fps: float,
    paused: bool,
) -> np.ndarray:
    """Single-camera operational view with compact, prominent metrics."""
    del threshold_masks
    display = config["display"]
    canvas_width = int(display["canvas_width"])
    canvas_height = int(display["canvas_height"])
    header = 78
    footer = 58
    margin = 16

    canvas = np.full(
        (canvas_height, canvas_width, 3),
        (18, 21, 27),
        dtype=np.uint8,
    )
    cv2.rectangle(canvas, (0, 0), (canvas_width, header), (28, 33, 41), -1)

    state_key = control.state.replace("HOLD_", "")
    state_color = STATE_COLORS.get(state_key, (110, 120, 135))
    if paused:
        state_color = (80, 80, 170)

    put_text(
        canvas,
        "UNITREE G1 | BLACK LINE VISION V3.1",
        (24, 34),
        0.78,
        (245, 247, 250),
        2,
    )
    put_text(
        canvas,
        f"{profile_name.upper()} | FPS {fps:5.1f} | Confidence {control.confidence * 100:5.1f}%",
        (24, 62),
        0.48,
        (135, 190, 255),
        1,
    )

    badge_w = 330
    rounded_rect(
        canvas,
        (canvas_width - badge_w - 24, 16),
        (canvas_width - 24, 62),
        state_color,
        radius=15,
    )
    state_text = "PAUSED" if paused else control.state
    text_size = cv2.getTextSize(
        state_text,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        2,
    )[0]
    put_text(
        canvas,
        state_text,
        (
            canvas_width - badge_w - 24
            + (badge_w - text_size[0]) // 2,
            48,
        ),
        0.72,
        (255, 255, 255),
        2,
    )

    scene = draw_scene_overlay(frame, result, config)
    scene_panel, _, _, _ = resize_letterbox(
        scene,
        canvas_width - margin * 2,
        canvas_height - header - footer - margin * 2,
    )
    y1 = header + margin
    y2 = canvas_height - footer - margin
    canvas[y1:y2, margin:canvas_width - margin] = scene_panel
    cv2.rectangle(
        canvas,
        (margin, y1),
        (canvas_width - margin, y2),
        (58, 66, 78),
        2,
    )

    angle = "N/A" if control.angle_deg is None else f"{control.angle_deg:+.2f} deg"
    lateral = (
        "N/A"
        if control.lateral_error_norm is None
        else f"{control.lateral_error_norm:+.4f}"
    )
    metrics = (
        f"Angle {angle} | Lateral {lateral} | "
        f"Yaw {control.yaw_command:+.3f} | "
        f"Side {control.lateral_command:+.3f} | "
        f"Forward {control.forward_command:+.3f}"
    )
    put_text(
        canvas,
        metrics,
        (24, canvas_height - 31),
        0.53,
        (235, 238, 242),
        1,
    )
    put_text(
        canvas,
        "1 Sensitive | 2 Balanced | 3 Strict | M Mask | D Line | R Reset | S Save | P Pause | Q Quit",
        (24, canvas_height - 10),
        0.40,
        (145, 154, 168),
        1,
    )
    return canvas

