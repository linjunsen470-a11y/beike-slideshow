# Agent guidance

This is a small personal tool: fetch a Beike listing and render its photos and facts into a 9:16 slideshow video. Keep changes practical and scoped; avoid CI, framework additions, repository restructuring, or dependency lockfile campaigns.

- No LLM calls in the fetch/render path, including BGM analysis and captions.
- Read the Beike key only from `~/.beike/BEIKE_MCP_API_KEY`. Never add an environment key override, print the key, inspect the real secret during maintenance, or commit secrets.
- The scheduler bot does not write code; Grok/Codex handles code changes.

Where to change things:

- `make_video.sh`: one-command orchestration, fetch/render flags, seed and template selection.
- `fetch_listing.py`: listing lookup, downloads, listing/manifest files and fetch cache; `beike_mcp.py`: MCP requests and file-only key loading.
- `build_slideshow.py`: rendering, timeline, captions, layouts and template registry. Keep `TEMPLATES_PLAN.md` aligned with template changes.
- `bgm_tools.py`: track selection, audio analysis/cache and loudness; `sfx_tools.py`: sound effects. Preserve `bgm/user/`, audio assets and `.analysis/` caches.
- `dump_plates.py`: preview helper; currently contains a listing-specific path, so inspect before running.
- `REPORT_*.md`: recent behavior and validation; `archive/`: historical tasks, logs and implementations, not runtime code.

Light checks: `bash -n make_video.sh`, parse changed Python files for syntax, and `python3 -B build_slideshow.py --help`. Do not fetch listings or read the key for a documentation-only change.

When rendering changes need a smoke test, use an existing `/workspace/ke-house-<id>/` with suitable images, and a distinct output filename:

```bash
./make_video.sh <id> --skip-fetch --seed 7 --width 270 --height 480 --fps 10 --preset ultrafast --output /workspace/ke-house-<id>/video/smoke.mp4
```

Check the exit status, duration, video and audio streams. This reduced-resolution smoke does not verify full-resolution typography. Preserve executable modes of existing scripts. Record changes and relevant checks in a short report; never commit secrets or generated logs/videos.
