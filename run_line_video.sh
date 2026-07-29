#!/usr/bin/env bash
set -euo pipefail

caller_dir="$PWD"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

if (( $# > 0 )); then
  line_source="$1"
  shift
  if [[ "$line_source" != /* && "$line_source" != *"://"* ]]; then
    line_source="$caller_dir/$line_source"
  fi
else
  line_source="$script_dir/../../lab/scripts/demo/line_video.mp4"
fi

if [[ -x .venv/bin/python ]]; then
  line_python=.venv/bin/python
elif [[ -x ../../lab/.venv-camera/bin/python ]]; then
  line_python=../../lab/.venv-camera/bin/python
else
  line_python=python3
fi

"$line_python" app.py \
  --source "$line_source" \
  --profile balanced \
  --preset-file video_processing_presets.yaml \
  --processing-preset stable \
  --loop-video \
  "$@"
