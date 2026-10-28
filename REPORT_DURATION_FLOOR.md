# Duration floor

Listings that lack room photos (no kitchen or bath) were finishing around 12.8–14.7s. `build_slideshow.py` then stopped with `Duration … is outside 15–20s`.

## What changed

Only `build_slideshow.py`. New helper `guard_reel_duration` replaces both total-duration stops (no-BGM path and BGM path, after phrase alignment).

- Total under 15s: print `Warning: duration …s is under 15s because of insufficient shots/material; continuing render.` and keep rendering.
- Total over 20s: still `parser.error` (`Duration …s is outside 15–20s`, with the previous `; insufficient or excessive material` suffix on the no-BGM path).
- BGM path still rejects a shot outside its `dur_lo`/`dur_hi` band (0.021s tolerance). A short total is allowed only when that is the only failure.
- Shot construction is unchanged. The same photo file is still not reused across shots.

Phrase alignment still prefers 15–20s when the per-shot bands can reach that window. This change only stops treating a short total as fatal.

## Checks

- `python3 -B build_slideshow.py --help` exited 0.
- `./make_video.sh 108406164038 --skip-fetch --template poster --seed 4` exited 0.
  - Template `poster`, seed `4`, duration **12.800s**.
  - Warning printed, then render continued.
  - Output: `/workspace/ke-house-108406164038/video/shidaizhongguoshidaitianyun_108406164038_9x16_poster.mp4` (4.84 MB).
  - `ffprobe`: H.264 1080×1920, AAC, duration 12.800s.
  - Timeline files were unique (community, floorplan, cover, two bedroom shots, end card). No kitchen or bath shot.
- Direct calls: 15.0s and 20.0s pass silently; 12.8s and 14.999s warn and return; 20.001s exits 2.

Nothing was uploaded.
