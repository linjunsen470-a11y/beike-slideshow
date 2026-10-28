# Slim package report

Deleted:
- `archive/` (historical code, tasks, reports, and logs).
- `bgm/bgm-house.zip` (its 20 MP3 names and sizes matched `bgm/user/`).
- `bgm/library/`, including its small analysis cache: optional fallback music, unused while the retained user tracks are available.
- `bgm/soft_ambient.mp3` and `bgm/soft_ambient_28s.m4a`: legacy audio, unused by current default selection.
- `reports/codex_hygiene.log`, `reports/codex_slim.log`.
- Root reports: `REPORT_HYGIENE.md`, `REPORT_v9.md`, `REPORT_v10.md`, `REPORT_MINFIX.md`, `REPORT_BGM.md`.
- `reports/REPORT_v2.md`, `reports/REPORT_v3.md`, `reports/REPORT_v7.md`, `reports/REPORT_v8.md`.
- `CODEX_TASK_SLIM.md`, `CODEX_TASK_HYGIENE.md`.

No MP4s, Python bytecode, or __pycache__ directories were present. Kept the tiny user analysis caches, template plan, all scripts, SFX, and both fonts: renderer code uses both bundled fonts. Updated README to describe the omitted fallback library and removed archive.

Remaining `bgm/user/` MP3 count: **20**, all unchanged (SHA-256 compared before/after).

Approximate remaining size (`du -sh`): **53M**. Still over ~25 MB uncompressed; the two required fonts account for about 40 MiB. No zip was created; compressed package size has not been measured.

Checks passed: `bash -n make_video.sh`; AST syntax parsing of all root Python scripts; `python3 -B build_slideshow.py --help`; seeded default user-track selection; Pillow loading both bundled fonts. Runtime code and script modes were unchanged. No listing fetch or render was needed; no secrets were accessed.
