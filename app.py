from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from controller import LineController
from models import ControlResult, VisionResult
from tracker import StableLineTracker
from tuning import apply_tuning, deep_merge
from ui import compose_dashboard
from vision import BlackTapeVision


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    data = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    )
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a mapping.")
    return data


def load_processing_presets(
    path: str | None,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    if path is None:
        return {}, None

    preset_path = Path(path)
    if not preset_path.exists():
        raise FileNotFoundError(
            f"Processing preset file not found: {preset_path}"
        )
    data = yaml.safe_load(
        preset_path.read_text(encoding="utf-8")
    ) or {}
    presets = data.get("presets", {})
    if not isinstance(presets, dict) or not presets:
        raise ValueError(
            f"Processing preset file has no presets: {preset_path}"
        )
    default_name = data.get("default")
    if default_name is not None and default_name not in presets:
        raise ValueError(
            f"Unknown default processing preset: {default_name}"
        )
    return presets, default_name


def parse_source(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def open_capture(
    source: int | str,
    camera_cfg: dict[str, Any],
) -> cv2.VideoCapture:
    if isinstance(source, int):
        capture = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(source)
    else:
        capture = cv2.VideoCapture(source)

    if not capture.isOpened():
        raise RuntimeError(f"Cannot open source: {source}")

    if isinstance(source, int):
        capture.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            int(camera_cfg["width"]),
        )
        capture.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            int(camera_cfg["height"]),
        )
        capture.set(
            cv2.CAP_PROP_FPS,
            int(camera_cfg["fps"]),
        )
        capture.set(
            cv2.CAP_PROP_BUFFERSIZE,
            int(camera_cfg["buffer_size"]),
        )
    return capture


class LatestFrameCapture:
    def __init__(
        self,
        source: int | str,
        camera_cfg: dict[str, Any],
        *,
        loop_file: bool = False,
        realtime_file: bool = True,
    ) -> None:
        self.capture = open_capture(source, camera_cfg)
        self.file_source = (
            isinstance(source, str)
            and Path(source).is_file()
        )
        self.loop_file = loop_file
        self.realtime_file = realtime_file
        source_fps = float(self.capture.get(cv2.CAP_PROP_FPS))
        self.file_frame_period = (
            1.0 / source_fps
            if self.file_source and source_fps > 1e-6
            else 0.0
        )
        self.next_file_frame_time: float | None = None
        self.looped = False
        self.ended = False
        self.threaded = (
            not self.file_source
            and bool(camera_cfg["use_latest_frame_thread"])
        )

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.latest_frame: np.ndarray | None = None
        self.latest_ok = False
        self.latest_sequence = 0
        self.returned_sequence = 0
        self.worker: threading.Thread | None = None

        if self.threaded:
            self.worker = threading.Thread(
                target=self._reader_loop,
                name="camera-reader",
                daemon=True,
            )
            self.worker.start()

    def _reader_loop(self) -> None:
        while not self.stop_event.is_set():
            ok, frame = self.capture.read()
            if not ok:
                time.sleep(0.005)
                continue
            with self.lock:
                self.latest_ok = True
                self.latest_frame = frame
                self.latest_sequence += 1

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self.threaded:
            self.looped = False
            if (
                self.file_source
                and self.realtime_file
                and self.file_frame_period > 0.0
            ):
                now = time.perf_counter()
                if self.next_file_frame_time is None:
                    self.next_file_frame_time = now
                elif now < self.next_file_frame_time:
                    time.sleep(self.next_file_frame_time - now)

            ok, frame = self.capture.read()
            if not ok and self.file_source and self.loop_file:
                self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.capture.read()
                self.looped = bool(ok)
            self.ended = self.file_source and not ok

            if (
                ok
                and self.file_source
                and self.realtime_file
                and self.file_frame_period > 0.0
            ):
                now = time.perf_counter()
                if self.looped or self.next_file_frame_time is None:
                    self.next_file_frame_time = now + self.file_frame_period
                else:
                    self.next_file_frame_time = max(
                        self.next_file_frame_time + self.file_frame_period,
                        now,
                    )
            return ok, frame

        with self.lock:
            if (
                not self.latest_ok
                or self.latest_frame is None
                or self.latest_sequence == self.returned_sequence
            ):
                return False, None
            self.returned_sequence = self.latest_sequence
            return True, self.latest_frame.copy()

    def release(self) -> None:
        self.stop_event.set()
        if self.worker is not None:
            self.worker.join(timeout=1.0)
        self.capture.release()


def save_snapshot(
    output_dir: Path,
    dashboard: np.ndarray,
    result: VisionResult,
    control: ControlResult,
    profile_name: str,
    config: dict[str, Any],
    tuning_loaded: bool,
) -> None:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    image_path = output_dir / f"line_v3_{timestamp}.jpg"
    json_path = output_dir / f"line_v3_{timestamp}.json"

    cv2.imwrite(str(image_path), dashboard)
    payload = {
        "profile": profile_name,
        "detection_mode": config["detection"]["mode"],
        "tuning_loaded": tuning_loaded,
        "state": control.state,
        "line_detected": control.line_detected,
        "line_end_detected": control.line_end_detected,
        "confidence": control.confidence,
        "angle_deg": control.angle_deg,
        "lateral_error_norm": control.lateral_error_norm,
        "yaw_command": control.yaw_command,
        "lateral_command": control.lateral_command,
        "forward_command": control.forward_command,
        "visible_length_px": result.visible_length_px,
        "forward_distance_cm": result.forward_distance_cm,
        "candidate_count": len(result.candidates),
    }
    json_path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    print(f"Saved: {image_path}")
    print(f"Saved: {json_path}")


def run_image(
    source: str,
    config: dict[str, Any],
    profile_name: str,
    tuning_loaded: bool,
) -> None:
    frame = cv2.imread(source)
    if frame is None:
        raise RuntimeError(f"Cannot read image: {source}")

    vision = BlackTapeVision(config, profile_name)
    tracker = StableLineTracker(config, profile_name)
    controller = LineController(config)

    raw_result, threshold_masks = vision.detect(frame)
    result = tracker.update(raw_result)
    control = controller.update(result, tracker.stale_updates)

    label = (
        f"{profile_name} | {config['detection']['mode']}"
        + (" | tuned" if tuning_loaded else "")
    )
    dashboard = compose_dashboard(
        frame,
        result,
        control,
        threshold_masks,
        config,
        label,
        fps=0.0,
        paused=False,
    )

    output_dir = Path(config["display"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    save_snapshot(
        output_dir,
        dashboard,
        result,
        control,
        profile_name,
        config,
        tuning_loaded,
    )

    cv2.imshow(str(config["display"]["window_name"]), dashboard)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def run_stream(
    source: int | str,
    config: dict[str, Any],
    initial_profile: str,
    tuning_loaded: bool,
    loop_video: bool,
    preset_base_config: dict[str, Any],
    processing_presets: dict[str, dict[str, Any]],
    initial_processing_preset: str | None,
) -> None:
    capture = LatestFrameCapture(
        source,
        config["camera"],
        loop_file=loop_video,
        realtime_file=True,
    )

    profile_name = initial_profile
    preset_names = list(processing_presets)
    preset_index = (
        preset_names.index(initial_processing_preset)
        if initial_processing_preset in preset_names
        else 0
    )
    processing_preset = (
        preset_names[preset_index]
        if preset_names
        else None
    )
    vision = BlackTapeVision(config, profile_name)
    tracker = StableLineTracker(config, profile_name)
    controller = LineController(config)

    output_dir = Path(config["display"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    paused = False
    last_dashboard: np.ndarray | None = None
    last_result: VisionResult | None = None
    last_control: ControlResult | None = None

    previous_time = time.perf_counter()
    fps = 0.0

    try:
        while True:
            if not paused:
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

                raw_result, threshold_masks = vision.detect(frame)
                result = tracker.update(raw_result)
                control = controller.update(
                    result,
                    tracker.stale_updates,
                )

                now = time.perf_counter()
                instant_fps = 1.0 / max(now - previous_time, 1e-6)
                fps = (
                    instant_fps
                    if fps == 0.0
                    else 0.90 * fps + 0.10 * instant_fps
                )
                previous_time = now

                label = (
                    f"{profile_name} | {config['detection']['mode']}"
                    + (
                        f" | {processing_preset}"
                        if processing_preset is not None
                        else ""
                    )
                    + (" | tuned" if tuning_loaded else "")
                )
                dashboard = compose_dashboard(
                    frame,
                    result,
                    control,
                    threshold_masks,
                    config,
                    label,
                    fps,
                    paused=False,
                )

                last_dashboard = dashboard
                last_result = result
                last_control = control

            if last_dashboard is not None:
                cv2.imshow(
                    str(config["display"]["window_name"]),
                    last_dashboard,
                )

            key = cv2.waitKey(1 if not paused else 30) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("p"):
                paused = not paused
                continue

            if key in (ord("1"), ord("2"), ord("3")):
                profile_name = {
                    ord("1"): "sensitive",
                    ord("2"): "balanced",
                    ord("3"): "strict",
                }[key]
                vision.set_profile(profile_name)
                tracker.set_profile(profile_name)
                vision.reset()
                tracker.reset()
                controller.reset()
                print(f"Profile: {profile_name}")
                continue

            if key in (ord("["), ord("]")) and preset_names:
                step = -1 if key == ord("[") else 1
                preset_index = (
                    preset_index + step
                ) % len(preset_names)
                processing_preset = preset_names[preset_index]
                config = deep_merge(
                    preset_base_config,
                    processing_presets[processing_preset],
                )
                vision = BlackTapeVision(config, profile_name)
                tracker = StableLineTracker(config, profile_name)
                controller = LineController(config)
                print(
                    f"Processing preset: {processing_preset}"
                )
                continue

            if key == ord("m"):
                config["display"]["show_mask_overlay"] = not bool(
                    config["display"]["show_mask_overlay"]
                )
                continue
            if key == ord("d"):
                config["display"]["show_debug_points"] = not bool(
                    config["display"]["show_debug_points"]
                )
                continue
            if key == ord("t"):
                config["display"]["show_threshold_panel"] = not bool(
                    config["display"]["show_threshold_panel"]
                )
                continue
            if key == ord("r"):
                vision.reset()
                tracker.reset()
                controller.reset()
                print("Tracker reset.")
                continue

            if (
                key == ord("s")
                and last_dashboard is not None
                and last_result is not None
                and last_control is not None
            ):
                save_snapshot(
                    output_dir,
                    last_dashboard,
                    last_result,
                    last_control,
                    profile_name,
                    config,
                    tuning_loaded,
                )
    finally:
        capture.release()
        cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Black tape line detector with hybrid brightness calibration."
        )
    )
    parser.add_argument(
        "--source",
        default="0",
        help="Camera index, video path, or image path.",
    )
    parser.add_argument(
        "--profile",
        choices=["sensitive", "balanced", "strict"],
        default="balanced",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--tuning",
        default=None,
        help=(
            "Tuning YAML. Default: value from config calibration.tuning_file."
        ),
    )
    parser.add_argument(
        "--no-tuning",
        action="store_true",
        help="Ignore saved calibration parameters.",
    )
    parser.add_argument(
        "--loop-video",
        action="store_true",
        help="Loop video-file sources and reset temporal tracking at each restart.",
    )
    parser.add_argument(
        "--preset-file",
        default=None,
        help="Optional YAML containing named processing configurations.",
    )
    parser.add_argument(
        "--processing-preset",
        default=None,
        help="Initial named processing configuration from --preset-file.",
    )
    parser.add_argument("--image", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_config = load_config(args.config)

    tuning_path: str | None
    if args.no_tuning:
        tuning_path = None
    elif args.tuning:
        tuning_path = args.tuning
    else:
        tuning_path = str(
            base_config["calibration"]["tuning_file"]
        )

    config, tuning_loaded = apply_tuning(
        base_config,
        tuning_path,
    )
    preset_base_config = config
    processing_presets, default_processing_preset = (
        load_processing_presets(args.preset_file)
    )
    processing_preset = (
        args.processing_preset
        if args.processing_preset is not None
        else default_processing_preset
    )
    if processing_preset is not None:
        if processing_preset not in processing_presets:
            raise ValueError(
                f"Unknown processing preset: {processing_preset}"
            )
        config = deep_merge(
            preset_base_config,
            processing_presets[processing_preset],
        )

    if tuning_loaded:
        print(f"Loaded tuning: {tuning_path}")
    else:
        print("Using config.yaml defaults.")

    if args.image:
        run_image(
            str(args.source),
            config,
            args.profile,
            tuning_loaded,
        )
    else:
        run_stream(
            parse_source(str(args.source)),
            config,
            args.profile,
            tuning_loaded,
            args.loop_video,
            preset_base_config,
            processing_presets,
            processing_preset,
        )


if __name__ == "__main__":
    main()
