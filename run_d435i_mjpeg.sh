#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

if [[ -x .venv/bin/python ]]; then
  line_python=.venv/bin/python
elif [[ -x ../../lab/.venv-camera/bin/python ]]; then
  line_python=../../lab/.venv-camera/bin/python
else
  line_python=python3
fi

d435i_color_url="http://172.28.182.149:8080/api/sensors/d435i/color/mjpeg?camera=d435i_head"

"$line_python" app.py \
  --source "$d435i_color_url" \
  --profile balanced \
  --preset-file video_processing_presets.yaml \
  --processing-preset stable \
  --no-tuning
