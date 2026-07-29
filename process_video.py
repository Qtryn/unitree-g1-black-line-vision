from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import load_config, load_processing_presets
from controller import LineController
from tracker import StableLineTracker
from tuning import deep_merge
from ui import draw_scene_overlay, put_text
from vision import BlackTapeVision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run black-line vision over a video and save annotations."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--preset-file",
        default="video_processing_presets.yaml",
    )
    parser.add_argument("--processing-preset", default="stable")
    parser.add_argument(
        "--profile",
        choices=["sensitive", "balanced", "strict"],
        default="balanced",
    )
    parser.add_argument("--max-frames", type=int, default=0)
    return parser.parse_args()


def annotate_status(
    frame: np.ndarray,
    state: str,
    detected: bool,
    confidence: float,
    angle_deg: float | None,
    lateral_error: float | None,
    preset: str,
) -> np.ndarray:
    output = frame.copy()
    height, width = output.shape[:2]
    panel_height = max(62, int(height * 0.09))
    overlay = output.copy()
    cv2.rectangle(
        overlay,
        (0, 0),
        (width, panel_height),
        (245, 245, 245),
        -1,
    )
    output = cv2.addWeighted(output, 0.20, overlay, 0.80, 0.0)

    scale = max(0.42, min(width, height) / 900.0)
    status = "FOUND" if detected else "HELD/LOST"
    put_text(
        output,
        f"{preset} | {status} | {state}",
        (12, int(panel_height * 0.40)),
        scale,
        (0, 0, 0),
        2,
    )
    angle_text = "---" if angle_deg is None else f"{angle_deg:+.1f} deg"
    error_text = (
        "---" if lateral_error is None else f"{lateral_error:+.3f}"
    )
    put_text(
        output,
        (
            f"confidence {confidence:.2f}   angle {angle_text}"
            f"   lateral {error_text}"
        ),
        (12, int(panel_height * 0.80)),
        scale * 0.88,
        (0, 0, 0),
        1,
    )
    return output


def open_writer(
    path: Path,
    fps: float,
    frame_size: tuple[int, int],
) -> cv2.VideoWriter:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        frame_size,
    )
    if not writer.isOpened():
        raise RuntimeError(f"Cannot open video writer: {path}")
    return writer


def mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else 0.0


def percentile(values: list[float], value: float) -> float:
    return float(np.percentile(values, value)) if values else 0.0


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_config = load_config(args.config)
    presets, _ = load_processing_presets(args.preset_file)
    if args.processing_preset not in presets:
        raise ValueError(
            f"Unknown processing preset: {args.processing_preset}"
        )
    config = deep_merge(
        base_config,
        presets[args.processing_preset],
    )

    capture = cv2.VideoCapture(args.source)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {args.source}")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0.0:
        fps = 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = open_writer(Path(args.output), fps, (width, height))

    vision = BlackTapeVision(config, args.profile)
    tracker = StableLineTracker(config, args.profile)
    controller = LineController(config)

    frame_count = 0
    raw_detection_count = 0
    tracked_count = 0
    held_count = 0
    confidence_values: list[float] = []
    raw_confidence_values: list[float] = []
    center_jumps: list[float] = []
    angle_jumps: list[float] = []
    states: Counter[str] = Counter()
    previous_center: float | None = None
    previous_angle: float | None = None
    started = time.perf_counter()

    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            if args.max_frames > 0 and frame_count >= args.max_frames:
                break

            raw_result, _ = vision.detect(frame)
            result = tracker.update(raw_result)
            control = controller.update(result, tracker.stale_updates)

            frame_count += 1
            raw_detection_count += int(raw_result.detected)
            tracked = (
                result.angle_deg is not None
                and result.lateral_error_norm is not None
                and result.confidence > 0.05
            )
            tracked_count += int(tracked)
            held_count += int(tracked and not result.detected)
            states[control.state] += 1

            if raw_result.detected:
                raw_confidence_values.append(float(raw_result.confidence))
            if tracked:
                confidence_values.append(float(result.confidence))
                center = float(result.lateral_error_norm)
                angle = float(result.angle_deg)
                if previous_center is not None:
                    center_jumps.append(abs(center - previous_center))
                if previous_angle is not None:
                    angle_jumps.append(abs(angle - previous_angle))
                previous_center = center
                previous_angle = angle

            annotated = draw_scene_overlay(frame, result, config)
            annotated = annotate_status(
                annotated,
                control.state,
                raw_result.detected,
                float(result.confidence),
                result.angle_deg,
                result.lateral_error_norm,
                args.processing_preset,
            )
            writer.write(annotated)

            if frame_count % 300 == 0:
                print(f"Processed {frame_count} frames", flush=True)
    finally:
        capture.release()
        writer.release()

    elapsed = max(time.perf_counter() - started, 1e-6)
    summary: dict[str, Any] = {
        "source": str(Path(args.source).resolve()),
        "output": str(Path(args.output).resolve()),
        "processing_preset": args.processing_preset,
        "profile": args.profile,
        "fps": fps,
        "width": width,
        "height": height,
        "frames": frame_count,
        "duration_seconds": frame_count / fps,
        "processing_fps": frame_count / elapsed,
        "raw_detection_frames": raw_detection_count,
        "raw_detection_rate": (
            raw_detection_count / frame_count if frame_count else 0.0
        ),
        "tracked_or_held_frames": tracked_count,
        "tracked_or_held_rate": (
            tracked_count / frame_count if frame_count else 0.0
        ),
        "held_frames": held_count,
        "mean_raw_confidence": mean(raw_confidence_values),
        "mean_tracked_confidence": mean(confidence_values),
        "center_jump_p95": percentile(center_jumps, 95.0),
        "angle_jump_deg_p95": percentile(angle_jumps, 95.0),
        "controller_states": dict(states),
    }
    summary_path = (
        Path(args.summary)
        if args.summary
        else Path(args.output).with_suffix(".json")
    )
    summary_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    print(f"Saved summary: {summary_path}")
    return summary


if __name__ == "__main__":
    run(parse_args())
