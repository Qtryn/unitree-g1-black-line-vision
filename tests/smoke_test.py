from __future__ import annotations

from pathlib import Path
import json
import sys

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from controller import LineController
from tracker import StableLineTracker
from vision import BlackTapeVision


def detect(config: dict, name: str) -> dict:
    image = cv2.imread(str(ROOT / "samples" / name))
    if image is None:
        raise RuntimeError(
            "Run tools/generate_test_images.py first."
        )

    vision = BlackTapeVision(config, "balanced")
    tracker = StableLineTracker(config, "balanced")
    controller = LineController(config)

    raw_result, _ = vision.detect(image)
    result = tracker.update(raw_result)
    control = controller.update(result, tracker.stale_updates)

    return {
        "detected": bool(result.detected),
        "confidence": float(result.confidence),
        "angle_deg": result.angle_deg,
        "lateral_error_norm": result.lateral_error_norm,
        "state": control.state,
    }


def main() -> None:
    config = yaml.safe_load(
        (ROOT / "config.yaml").read_text(encoding="utf-8")
    )

    results = {}
    for name in [
        "line_center.jpg",
        "line_left.jpg",
        "line_right.jpg",
    ]:
        item = detect(config, name)
        results[name] = item
        assert item["detected"]
        assert item["confidence"] > 0.25
        assert item["angle_deg"] is not None
        assert item["lateral_error_norm"] is not None

    no_line = detect(config, "no_line_distractors.jpg")
    results["no_line_distractors.jpg"] = no_line
    assert not no_line["detected"]

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
