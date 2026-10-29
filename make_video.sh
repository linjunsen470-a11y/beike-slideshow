#!/usr/bin/env bash
# One implementation for Windows, Linux and macOS. No LLM calls.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
  exec python3 -X utf8 -B "$here/make_video.py" "$@"
fi
exec python -X utf8 -B "$here/make_video.py" "$@"
