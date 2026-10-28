# Minimal fix: short duration when photos are missing

## Context
Listing 108406164038 (sale, 时代中国时代天韵) has no kitchen/bathroom photos. Timeline ends at 12.8–14.7s across all templates/seeds. `build_slideshow.py` then errors: `Duration X.XXXs is outside 15–20s`. User wants a **minimal** fix only (personal tool; no over-engineering). Scheduler bot does not write code; you do.

## Goal
When planned duration is under 15s because of missing room shots, automatically lengthen the timeline into 15–20s **without**:
- reusing the same source photo in multiple shots
- hard cuts / shake
- changing the 15–20s product requirement for normal listings
- adding frameworks, CI, or large refactors

## Preferred minimal approach (pick the smallest that works)
1. Prefer: if unused community (or other unused, never-before-used) photos remain in the manifest, insert one extra non-cover community / living / bedroom shot using an unused file, within existing duration bands, so total lands in 15–20s.
2. Or: when after existing beat-sync / band fill the total is still <15s, proportionally stretch shot durations **slightly above** current `dur_hi` only as far as needed to reach ~15.5–17.5s (cap stretch so no single shot becomes absurd; keep transitions visible). Prefer stretching room/community shots over floorplan/end if needed.
3. Keep “same photo file in at most one shot”.

Do **not** lower the 15s floor. Do **not** add new CLI flags unless truly necessary.

## Verify
1. Syntax / help: `python3 -B build_slideshow.py --help`
2. Smoke on existing assets (do not fetch; do not print Beike key):
   ```bash
   ./make_video.sh 108406164038 --skip-fetch --template poster --seed 4 --output /workspace/ke-house-108406164038/video/smoke_duration.mp4
   ```
   Expect exit 0 and duration in 15–20s (full res OK if quick; otherwise also try reduced `--width 270 --height 480 --fps 10 --preset ultrafast` first then one full run).
3. Confirm no photo file is reused across shots (timeline JSON).
4. Write `REPORT_DURATION_FLOOR.md` with: what changed (files + behavior), how underfilled timelines are topped up, smoke result (duration, template, seed), residual risks.

## Out of scope
No Drive/Weiyun upload, no email, no unrelated refactors, no template redesign.

Preserve executable bits. Never commit secrets.
