Minimal fix only in /workspace/ke-slideshow (personal tool; no over-engineering).

Problem: listings missing kitchen/bath photos finish at ~12.8–14.7s and build_slideshow.py errors with "Duration … is outside 15–20s" (lines ~3103–3104 and ~3163–3165).

User now says under 15s is OK for such cases. Change behavior:
- If duration < 15s because of insufficient shots/material: print a clear warning and CONTINUE rendering (do not parser.error).
- If duration > 20s: still error (or keep existing over-cap handling).
- Keep per-shot band checks when BGM path is used, but if the ONLY failure is total <15s, allow it.
- Do not reuse the same photo file across shots. No new frameworks/CI. No unrelated refactors.

Verify:
1. python3 -B build_slideshow.py --help
2. ./make_video.sh 108406164038 --skip-fetch --template poster --seed 4
   Expect exit 0 and an mp4 even if duration is ~14s.
3. Write REPORT_DURATION_FLOOR.md (what changed, smoke duration/template/seed).

Do not upload anywhere. Do not print secrets.
