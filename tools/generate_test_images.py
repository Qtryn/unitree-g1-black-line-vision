from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def base_floor(width: int, height: int) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width]
    illumination = (
        185
        + 45 * yy / height
        + 14 * np.sin(xx / 160.0)
    )
    image = np.clip(
        illumination[..., None],
        0,
        255,
    ).astype(np.uint8)
    return np.repeat(image, 3, axis=2)


def add_noise_and_distractors(
    image: np.ndarray,
    seed: int,
) -> np.ndarray:
    result = image.copy()
    cv2.rectangle(
        result,
        (70, 430),
        (245, 560),
        (46, 46, 46),
        -1,
    )
    cv2.circle(
        result,
        (1090, 520),
        72,
        (42, 42, 42),
        -1,
    )

    rng = np.random.default_rng(seed)
    for _ in range(180):
        x = int(rng.integers(0, result.shape[1]))
        y = int(rng.integers(250, result.shape[0]))
        radius = int(rng.integers(1, 5))
        value = int(rng.integers(120, 225))
        cv2.circle(
            result,
            (x, y),
            radius,
            (value, value, value),
            -1,
        )
    return result


def main() -> None:
    output_dir = Path("samples")
    output_dir.mkdir(parents=True, exist_ok=True)

    width, height = 1280, 720
    scenes = {
        "line_center.jpg": np.asarray(
            [[575, 719], [705, 719], [678, 205], [635, 205]]
        ),
        "line_left.jpg": np.asarray(
            [[290, 719], [420, 719], [570, 220], [528, 220]]
        ),
        "line_right.jpg": np.asarray(
            [[860, 719], [990, 719], [730, 210], [686, 210]]
        ),
    }

    for index, (name, polygon) in enumerate(scenes.items()):
        image = add_noise_and_distractors(
            base_floor(width, height),
            seed=30 + index,
        )
        cv2.fillPoly(
            image,
            [polygon.astype(np.int32)],
            (16, 16, 16),
        )
        cv2.imwrite(str(output_dir / name), image)
        print(output_dir / name)

    no_line = add_noise_and_distractors(
        base_floor(width, height),
        seed=99,
    )
    cv2.imwrite(
        str(output_dir / "no_line_distractors.jpg"),
        no_line,
    )
    print(output_dir / "no_line_distractors.jpg")


if __name__ == "__main__":
    main()
