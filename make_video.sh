#!/usr/bin/env bash
# No-LLM one-shot: fetch a Beike listing, then render a 9:16 slideshow.
#   ./make_video.sh <house_id> [--skip-fetch] [--force] [--city 城市] [--type auto|sale|new|rent]
#                   [--template name|random] [--seed N] [renderer args...]
# Default template is random. A missing --seed is drawn and logged with the chosen template.
# BGM defaults to a seeded random bgm/user track (library fallback); --bgm <file|folder>
# and --bgm-track <name> override selection. Reuse --seed N to reproduce a pick.
# The API key is read by fetch_listing.py from ~/.beike/BEIKE_MCP_API_KEY. This script never prints it.
set -euo pipefail
id="${1:?usage: make_video.sh <house_id> [--skip-fetch] [--force] [--city 城市] [--type auto|sale|new|rent] [--template name|random] [--seed N] [renderer args...]}"
shift
here="$(cd "$(dirname "$0")" && pwd)"
house="/workspace/ke-house-${id}"

skip=0
fetch_args=()
render_args=()
template=""
seed=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-fetch)
      skip=1
      shift
      ;;
    --force)
      fetch_args+=(--force)
      shift
      ;;
    --city|--type)
      if [[ $# -lt 2 ]]; then
        echo "[make_video] missing value for $1" >&2
        exit 2
      fi
      fetch_args+=("$1" "$2")
      shift 2
      ;;
    --template)
      if [[ $# -lt 2 ]]; then
        echo "[make_video] missing value for --template" >&2
        exit 2
      fi
      template="$2"
      shift 2
      ;;
    --seed)
      if [[ $# -lt 2 ]]; then
        echo "[make_video] missing value for --seed" >&2
        exit 2
      fi
      seed="$2"
      shift 2
      ;;
    *)
      render_args+=("$1")
      shift
      ;;
  esac
done

if [[ "$skip" -eq 0 ]]; then
  python3 -u "$here/fetch_listing.py" "$id" --out-dir "$house" "${fetch_args[@]}"
else
  echo "[make_video] --skip-fetch: using existing files in $house" >&2
fi

if [[ -z "$seed" ]]; then
  seed="$(python3 -c 'import secrets; print(secrets.randbelow(2147483646) + 1)')"
fi

# Resolve random here so the log line names the template before the renderer starts.
# resolve_template_name uses the same TEMPLATE_ORDER as build_slideshow.py.
template="$(python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import build_slideshow as b
name, _seed = b.resolve_template_name(sys.argv[2], int(sys.argv[3]), "0")
print(name)
' "$here" "${template:-random}" "$seed")"

echo "[make_video] template=${template} seed=${seed}"

exec python3 -u "$here/build_slideshow.py" --house-dir "$house" \
  --template "$template" --seed "$seed" "${render_args[@]}"
