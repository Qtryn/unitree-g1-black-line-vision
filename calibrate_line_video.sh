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

"$line_python" calibrate_parameters.py \
  --source ../../lab/scripts/demo/line_video.mp4 \
  --profile balanced
