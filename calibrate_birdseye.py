from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import yaml


clicked_points: list[tuple[int, int]] = []


def callback(
    event: int,
    x: int,
    y: int,
    flags: int,
    userdata: object,
) -> None:
    del flags, userdata

    if event == cv2.EVENT_LBUTTONDOWN:
        if len(clicked_points) < 4:
            clicked_points.append((x, y))

    if event == cv2.EVENT_RBUTTONDOWN and clicked_points:
        clicked_points.pop()


def order_points(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype=np.float32)
    point_sum = points.sum(axis=1)
    point_diff = np.diff(points, axis=1).reshape(-1)

    ordered[0] = points[np.argmin(point_sum)]
    ordered[2] = points[np.argmax(point_sum)]
    ordered[1] = points[np.argmin(point_diff)]
    ordered[3] = points[np.argmax(point_diff)]
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="0")
    parser.add_argument(
        "--output",
        default="calibration/homography.yaml",
    )
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument(
        "--pixels-per-cm-x",
        type=float,
        default=0.0,
    )
    parser.add_argument(
        "--pixels-per-cm-y",
        type=float,
        default=0.0,
    )
    args = parser.parse_args()

    try:
        source: int | str = int(args.source)
    except ValueError:
        source = args.source

    capture = (
        cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if isinstance(source, int)
        else cv2.VideoCapture(source)
    )

    if not capture.isOpened():
        raise RuntimeError(f"Cannot open source: {source}")

    ok, frame = capture.read()
    capture.release()

    if not ok or frame is None:
        raise RuntimeError("Cannot capture calibration frame.")

    window = "Bird-eye calibration"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, callback)

    print(
        "Left-click 4 floor corners. Right-click removes "
        "the last point. Enter saves. R resets. Esc cancels."
    )

    while True:
        canvas = frame.copy()

        for index, point in enumerate(clicked_points):
            cv2.circle(canvas, point, 7, (0, 0, 255), -1)
            cv2.putText(
                canvas,
                str(index + 1),
                (point[0] + 8, point[1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )

        if len(clicked_points) == 4:
            polygon = np.asarray(
                clicked_points,
                dtype=np.int32,
            ).reshape((-1, 1, 2))
            cv2.polylines(
                canvas,
                [polygon],
                True,
                (0, 255, 0),
                2,
            )

        cv2.imshow(window, canvas)
        key = cv2.waitKey(30) & 0xFF

        if key == 27:
            cv2.destroyAllWindows()
            return
        if key == ord("r"):
            clicked_points.clear()
        if key in (10, 13) and len(clicked_points) == 4:
            break

    source_points = order_points(
        np.asarray(clicked_points, dtype=np.float32)
    )
    destination_points = np.asarray(
        [
            [0, 0],
            [args.width - 1, 0],
            [args.width - 1, args.height - 1],
            [0, args.height - 1],
        ],
        dtype=np.float32,
    )

    homography = cv2.getPerspectiveTransform(
        source_points,
        destination_points,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "homography": homography.tolist(),
        "source_points": source_points.tolist(),
        "output_width": args.width,
        "output_height": args.height,
        "pixels_per_cm_x": args.pixels_per_cm_x,
        "pixels_per_cm_y": args.pixels_per_cm_y,
    }

    output_path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Saved: {output_path}")

    preview = cv2.warpPerspective(
        frame,
        homography,
        (args.width, args.height),
    )
    cv2.imshow("Bird-eye preview", preview)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
