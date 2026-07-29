from __future__ import annotations

import argparse
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from app import LatestFrameCapture, load_config, parse_source
from controller import LineController
from tracker import StableLineTracker
from tuning import apply_tuning, save_tuning
from ui import draw_scene_overlay, put_text, resize_letterbox
from vision import BlackTapeVision, odd


MODE_NAMES = ["gray_fixed", "adaptive", "hsv_black", "hybrid"]
CONTROL_WINDOW = "V3 Calibration Controls"
PREVIEW_WINDOW = "V3 Calibration Preview"


def nothing(_: int) -> None:
    pass


def create_trackbar(
    name: str,
    value: int,
    maximum: int,
) -> None:
    cv2.createTrackbar(
        name,
        CONTROL_WINDOW,
        int(np.clip(value, 0, maximum)),
        maximum,
        nothing,
    )


def get(name: str) -> int:
    return cv2.getTrackbarPos(name, CONTROL_WINDOW)


def set_value(name: str, value: int) -> None:
    cv2.setTrackbarPos(name, CONTROL_WINDOW, int(value))


def initial_values(
    config: dict[str, Any],
    profile_name: str,
) -> dict[str, int]:
    profile = config["profiles"][profile_name]
    detection = config["detection"]
    segmentation = config["segmentation"]
    line_model = config["line_model"]
    roi = config["roi"]

    mode_name = str(detection["mode"])
    mode_index = (
        MODE_NAMES.index(mode_name)
        if mode_name in MODE_NAMES
        else 3
    )

    return {
        "Mode 0G 1A 2V 3H": mode_index,
        "Gray max": int(detection["gray_max"]),
        "HSV V max": int(detection["hsv_v_max"]),
        "HSV S max": int(detection["hsv_s_max"]),
        "Very dark": int(detection["very_dark_max"]),
        "Vote required": int(detection["vote_required"]),
        "Use Otsu": int(bool(detection["enable_otsu"])),
        "Use Blackhat": int(bool(detection["enable_blackhat"])),
        "Adaptive block": int(segmentation["adaptive_block_size"]),
        "Adaptive C": int(profile["adaptive_c"]),
        "Blackhat thr": int(segmentation["blackhat_threshold"]),
        "CLAHE x10": int(float(segmentation["clahe_clip_limit"]) * 10),
        "Close kernel": int(segmentation["close_kernel"]),
        "Close iter": int(segmentation["close_iterations"]),
        "Open kernel": int(segmentation["open_kernel"]),
        "Open iter": int(segmentation["open_iterations"]),
        "Min area x10000": int(
            float(profile["min_component_area_ratio"]) * 10000
        ),
        "Min elong x10": int(float(profile["min_elongation"]) * 10),
        "Min vertical %": int(
            float(segmentation["min_vertical_span_ratio"]) * 100
        ),
        "Min bottom %": int(
            float(segmentation["min_bottom_proximity"]) * 100
        ),
        "Min contrast %": int(
            float(segmentation["min_dark_contrast"]) * 100
        ),
        "Continuity %": int(
            float(line_model["min_continuity_ratio"]) * 100
        ),
        "Max width CV %": int(
            float(line_model["max_width_cv"]) * 100
        ),
        "ROI top %": int(float(roi["top_ratio"]) * 100),
        "ROI left %": int(float(roi["left_ratio"]) * 100),
        "ROI right %": int(float(roi["right_ratio"]) * 100),
        "Lookahead %": int(
            float(line_model["lookahead_y_ratio"]) * 100
        ),
    }


def create_controls(values: dict[str, int]) -> None:
    cv2.namedWindow(CONTROL_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(CONTROL_WINDOW, 560, 940)

    maxima = {
        "Mode 0G 1A 2V 3H": 3,
        "Gray max": 255,
        "HSV V max": 255,
        "HSV S max": 255,
        "Very dark": 120,
        "Vote required": 5,
        "Use Otsu": 1,
        "Use Blackhat": 1,
        "Adaptive block": 101,
        "Adaptive C": 30,
        "Blackhat thr": 80,
        "CLAHE x10": 60,
        "Close kernel": 51,
        "Close iter": 5,
        "Open kernel": 31,
        "Open iter": 4,
        "Min area x10000": 200,
        "Min elong x10": 80,
        "Min vertical %": 100,
        "Min bottom %": 100,
        "Min contrast %": 100,
        "Continuity %": 100,
        "Max width CV %": 200,
        "ROI top %": 85,
        "ROI left %": 45,
        "ROI right %": 100,
        "Lookahead %": 98,
    }

    for name, value in values.items():
        create_trackbar(name, value, maxima[name])


def apply_controls(
    config: dict[str, Any],
    profile_name: str,
) -> dict[str, Any]:
    mode_index = int(np.clip(get("Mode 0G 1A 2V 3H"), 0, 3))
    config["detection"]["mode"] = MODE_NAMES[mode_index]
    config["detection"]["gray_max"] = max(1, get("Gray max"))
    config["detection"]["hsv_v_max"] = max(1, get("HSV V max"))
    config["detection"]["hsv_s_max"] = get("HSV S max")
    config["detection"]["very_dark_max"] = max(1, get("Very dark"))
    config["detection"]["vote_required"] = max(1, get("Vote required"))
    config["detection"]["enable_otsu"] = bool(get("Use Otsu"))
    config["detection"]["enable_blackhat"] = bool(get("Use Blackhat"))

    config["segmentation"]["adaptive_block_size"] = odd(
        get("Adaptive block")
    )
    config["profiles"][profile_name]["adaptive_c"] = get("Adaptive C")
    config["segmentation"]["blackhat_threshold"] = get("Blackhat thr")
    config["segmentation"]["clahe_clip_limit"] = max(
        0.1,
        get("CLAHE x10") / 10.0,
    )
    config["segmentation"]["close_kernel"] = odd(get("Close kernel"))
    config["segmentation"]["close_iterations"] = get("Close iter")
    config["segmentation"]["open_kernel"] = odd(get("Open kernel"))
    config["segmentation"]["open_iterations"] = get("Open iter")

    config["profiles"][profile_name]["min_component_area_ratio"] = max(
        0.0001,
        get("Min area x10000") / 10000.0,
    )
    config["profiles"][profile_name]["min_elongation"] = max(
        1.0,
        get("Min elong x10") / 10.0,
    )
    config["segmentation"]["min_vertical_span_ratio"] = (
        get("Min vertical %") / 100.0
    )
    config["segmentation"]["min_bottom_proximity"] = (
        get("Min bottom %") / 100.0
    )
    config["segmentation"]["min_dark_contrast"] = (
        get("Min contrast %") / 100.0
    )
    config["line_model"]["min_continuity_ratio"] = (
        get("Continuity %") / 100.0
    )
    config["line_model"]["max_width_cv"] = max(
        0.05,
        get("Max width CV %") / 100.0,
    )

    top = min(get("ROI top %"), 94) / 100.0
    left = min(get("ROI left %"), 89) / 100.0
    right = max(get("ROI right %"), int(left * 100) + 5) / 100.0
    right = min(right, 1.0)

    config["roi"]["top_ratio"] = top
    config["roi"]["left_ratio"] = left
    config["roi"]["right_ratio"] = right
    config["line_model"]["lookahead_y_ratio"] = max(
        0.10,
        get("Lookahead %") / 100.0,
    )
    return config


def export_tuning(
    config: dict[str, Any],
    profile_name: str,
) -> dict[str, Any]:
    return {
        "roi": deepcopy(config["roi"]),
        "detection": deepcopy(config["detection"]),
        "segmentation": {
            key: deepcopy(config["segmentation"][key])
            for key in (
                "clahe_clip_limit",
                "adaptive_block_size",
                "blackhat_threshold",
                "close_kernel",
                "close_iterations",
                "open_kernel",
                "open_iterations",
                "min_vertical_span_ratio",
                "min_bottom_proximity",
                "min_dark_contrast",
            )
        },
        "profiles": {
            profile_name: {
                key: deepcopy(config["profiles"][profile_name][key])
                for key in (
                    "adaptive_c",
                    "min_component_area_ratio",
                    "min_elongation",
                    "hold_updates",
                )
            }
        },
        "line_model": {
            key: deepcopy(config["line_model"][key])
            for key in (
                "min_continuity_ratio",
                "max_width_cv",
                "lookahead_y_ratio",
            )
        },
    }


def title_image(
    image: np.ndarray,
    title: str,
) -> np.ndarray:
    result = image.copy()
    cv2.rectangle(result, (0, 0), (result.shape[1], 42), (25, 29, 36), -1)
    put_text(result, title, (14, 29), 0.64, (245, 247, 250), 2)
    return result


def mask_to_bgr(mask: np.ndarray) -> np.ndarray:
    if mask.ndim == 3:
        return mask
    return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)


def compose_calibration_preview(
    frame: np.ndarray,
    result: Any,
    control: Any,
    masks: dict[str, np.ndarray],
    config: dict[str, Any],
    profile_name: str,
    fps: float,
    paused: bool,
) -> np.ndarray:
    """Show only the camera and selected line, as requested.

    Trackbars remain in the separate Controls window. The preview is kept
    uncluttered so the operator can focus on whether the correct tape line is
    selected while tuning parameters.
    """
    del masks
    width, height = 1500, 860
    header = 76
    footer = 58
    margin = 16

    canvas = np.full((height, width, 3), (17, 20, 26), dtype=np.uint8)
    cv2.rectangle(canvas, (0, 0), (width, header), (28, 33, 41), -1)

    mode = str(config["detection"]["mode"])
    locked = result.detected or control.confidence > 0.05
    status = "LINE LOCKED" if locked else "NO VALID LINE"
    status_color = (65, 210, 105) if locked else (75, 85, 225)

    put_text(
        canvas,
        "BLACK LINE CALIBRATION V3.1",
        (22, 33),
        0.78,
        (245, 247, 250),
        2,
    )
    put_text(
        canvas,
        f"{profile_name.upper()} | {mode.upper()} | FPS {fps:4.1f}",
        (22, 61),
        0.48,
        (130, 190, 255),
        1,
    )

    badge_w = 310
    cv2.rectangle(
        canvas,
        (width - badge_w - 22, 17),
        (width - 22, 60),
        status_color,
        -1,
    )
    put_text(
        canvas,
        status,
        (width - badge_w + 4, 47),
        0.66,
        (255, 255, 255),
        2,
    )

    scene = draw_scene_overlay(frame, result, config)
    scene_panel, _, _, _ = resize_letterbox(
        scene,
        width - margin * 2,
        height - header - footer - margin * 2,
    )
    y1 = header + margin
    y2 = height - footer - margin
    canvas[y1:y2, margin:width - margin] = scene_panel
    cv2.rectangle(
        canvas,
        (margin, y1),
        (width - margin, y2),
        (58, 66, 78),
        2,
    )

    angle = "N/A" if control.angle_deg is None else f"{control.angle_deg:+.2f} deg"
    lateral = (
        "N/A"
        if control.lateral_error_norm is None
        else f"{control.lateral_error_norm:+.4f}"
    )
    footer_text = (
        f"State {control.state} | Confidence {control.confidence * 100:5.1f}% | "
        f"Angle {angle} | Lateral {lateral} | "
        "S Save | P Pause | R Reset | Q Quit"
    )
    put_text(
        canvas,
        footer_text,
        (22, height - 20),
        0.48,
        (185, 193, 205),
        1,
    )

    if paused:
        cv2.rectangle(canvas, (0, 0), (width, height), (25, 25, 25), 12)
        put_text(canvas, "PAUSED", (width - 155, height - 20), 0.68, (80, 170, 255), 2)

    return canvas

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive black-line parameter calibration."
    )
    parser.add_argument("--source", default="0")
    parser.add_argument(
        "--profile",
        choices=["sensitive", "balanced", "strict"],
        default="balanced",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--output",
        default=None,
        help="Output tuning YAML. Defaults to calibration.tuning_file.",
    )
    parser.add_argument(
        "--load-existing",
        action="store_true",
        help="Start from an existing saved tuning file when available.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_config = load_config(args.config)
    output_path = args.output or str(
        base_config["calibration"]["tuning_file"]
    )

    if args.load_existing:
        config, loaded = apply_tuning(base_config, output_path)
        if loaded:
            print(f"Loaded existing tuning: {output_path}")
    else:
        config = deepcopy(base_config)

    defaults = initial_values(config, args.profile)
    create_controls(defaults)
    cv2.namedWindow(PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(PREVIEW_WINDOW, 1500, 860)

    capture = LatestFrameCapture(
        parse_source(str(args.source)),
        config["camera"],
        loop_file=True,
        realtime_file=True,
    )
    vision = BlackTapeVision(config, args.profile)
    tracker = StableLineTracker(config, args.profile)
    controller = LineController(config)

    paused = False
    last_frame: np.ndarray | None = None
    last_preview: np.ndarray | None = None
    previous_signature: tuple[int, ...] | None = None
    previous_time = time.perf_counter()
    fps = 0.0

    try:
        while True:
            signature = tuple(get(name) for name in defaults)
            config = apply_controls(config, args.profile)

            if signature != previous_signature:
                # Keep the temporal lock from fighting large calibration changes.
                vision.reset()
                tracker.reset()
                controller.reset()
                previous_signature = signature

            if not paused or last_frame is None:
                ok, frame = capture.read()
                if not ok or frame is None:
                    if capture.ended:
                        break
                    time.sleep(0.005)
                    continue
                if capture.looped:
                    vision.reset()
                    tracker.reset()
                    controller.reset()
                    previous_time = time.perf_counter()
                    fps = 0.0
                last_frame = frame
            else:
                frame = last_frame.copy()

            raw_result, masks = vision.detect(frame)
            stable_result = tracker.update(raw_result)
            control = controller.update(stable_result, tracker.stale_updates)

            now = time.perf_counter()
            instant = 1.0 / max(now - previous_time, 1e-6)
            fps = instant if fps == 0 else 0.90 * fps + 0.10 * instant
            previous_time = now

            preview = compose_calibration_preview(
                frame,
                raw_result,
                control,
                masks,
                config,
                args.profile,
                fps,
                paused,
            )
            last_preview = preview
            cv2.imshow(PREVIEW_WINDOW, preview)

            key = cv2.waitKey(1 if not paused else 30) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("p"):
                paused = not paused
                continue
            if key == ord("r"):
                vision.reset()
                tracker.reset()
                controller.reset()
                print("Tracker reset.")
                continue
            if key == ord("s"):
                tuning = export_tuning(config, args.profile)
                save_tuning(output_path, tuning)
                print(f"Saved tuning: {output_path}")
                if last_preview is not None:
                    snapshot_path = Path(output_path).with_suffix(".jpg")
                    cv2.imwrite(str(snapshot_path), last_preview)
                    print(f"Saved preview: {snapshot_path}")
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
