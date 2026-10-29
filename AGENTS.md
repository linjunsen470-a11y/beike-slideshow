# Agent guidance

This is a small personal tool: fetch a Beike listing and render its photos and facts into a 9:16 slideshow video. Keep changes practical and scoped; avoid CI, framework additions, repository restructuring, or dependency lockfile campaigns.

- No LLM calls in the fetch/render path, including BGM analysis and captions.
- Read the Beike key only from `~/.beike/BEIKE_MCP_API_KEY`. Never add an environment key override, print the key, inspect the real secret during maintenance, or commit secrets.
- The scheduler bot does not write code; Grok/Codex handles code changes.

Where to change things:

- `make_video.py` / `make_video.sh`: one-command orchestration, fetch/render flags, seed and template selection.
- `fetch_listing.py`: listing lookup, downloads, listing/manifest files and fetch cache; `beike_mcp.py`: MCP requests and file-only key loading.
- `remote_edit_images.py`: optional paid batch photo editing; `image_edit_api.py`: Gemini/OpenAI request adapters. Default to the economy model, bounded concurrency, no automatic retries or model upgrades.
- `build_slideshow.py`: render CLI and encoding. `slideshow_templates.py`: the five recommended layouts; `slideshow_layouts.py`: shared typography and legacy layouts; `slideshow_engine.py`: timeline/motion/frame composition; `slideshow_common.py`: primitives, fonts and template registry. Keep `TEMPLATES_PLAN.md` aligned with template changes.
- `bgm_tools.py`: track selection, audio analysis/cache and loudness; `sfx_tools.py`: sound effects. Preserve `bgm/user/`, audio assets and `.analysis/` caches.
- `preview_composition.py`: explicit local preview, one contact sheet, requires `--house-dir`.
- Normal rendering produces only MP4. Detailed review output is opt-in with `--diagnostics`; do not restore automatic transition repair/proof gates.
- Keep current behavior in README.md and TEMPLATES_PLAN.md. Record maintenance checks briefly in README.md; do not create per-run reports. `archive/` holds local compressed history, not runtime code or current instructions.

## User preference: fast visual iteration (2026-10-29)

For video-style tuning, prioritize quickly making a visible sample. Do not add or
run engineering test suites, regression matrices, multiple smoke renders, or
exhaustive frame/decode checks. Make the requested visual change, inspect a few
representative frames, and render one sample using existing local material and
the same music. Check only obvious layout problems and successful video output.
Keep the change report brief. Broader testing is for an explicit user request or
a concrete failure that needs diagnosis. This supersedes the routine checks below
for visual-only iterations.

Visual preference clarified with marked screenshots: avoid large blank outer
bands. For the current story review, use approximately 32px top/bottom margins
at 1080×1920 and let photos occupy the remaining height. Do not restore the
old automatic 144px vertical text inset or leave unused space below captions.

For other code changes, light checks: `bash -n make_video.sh`, parse changed Python files for syntax, and `python3 -B build_slideshow.py --help`. Do not fetch listings or read the key for a documentation-only change.

When rendering changes need a smoke test, use an existing local listing folder with suitable images, and a distinct output filename:

```bash
python -B make_video.py <id> --skip-fetch --seed 7 --width 270 --height 480 --fps 10 --preset ultrafast --output data/ke-house-<id>/video/smoke.mp4
```

Check the exit status, duration, video and audio streams. This reduced-resolution smoke does not verify full-resolution typography. Preserve executable modes of existing scripts. Record changes and relevant checks briefly in README.md; never commit secrets or generated logs/videos.
