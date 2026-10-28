# Slideshow template plan (v10)

Four presets share one timeline: 1080×1920, 30 fps, 15–20 s, the sale/new/rent shot order, phrase-synced soft BGM, no shake, no hard cut, no reused source image, pure black empty space, full-frame photos (never blurred to fill), and the same Noto Serif / Noto Sans CJK Black faces. 花字 stays at least 48 px; titles and the price numerals stay at least 120 px. Text, including stroke and shadow, stays at least 60 px inside the frame. What changes is the composition.

Selection: `build_slideshow.py --template <name>|random --seed N`. `make_video.sh` defaults to `random`, draws a seed when one is not passed, logs `template` and `seed`, and writes `<pinyin>_<id>_9x16_<template>.mp4`.

## gold_classic

The current v4d board, kept as the reference look.

- Cover: left gold block (location), serif community name, gold-gradient price, unit beside the price when it fits and on the next line when it does not, photo, chips under the photo.
- Title cards: gold block, serif title overlapping the photo top by 40 px, outlined pills under the photo.
- Captions: left row of gold-outline pills; the first pill on a hero is filled.
- Transitions (`impact`): whip, zoom_blur, flash, glitch, light_leak, spin, push, wipe, zoom.
- End card: left-aligned name and price, then a one-column label / value sheet with hairlines.

## editorial

A magazine column. The photograph sits above the type; nothing overlaps the picture.

- Cover: full-width photo on top. Under it, on black: gold tracked kicker, serif name, short gold rule, gold price, unit, then a middot spec line.
- Title cards: same column under the photo (kicker, title, rule, spec). No pills, no title sitting on the photo.
- Captions: one spec line under the title block (`3室2厅  ·  99㎡  ·  朝南`), gold middots, ink words. Left, not pills.
- Transitions (`glide`): wipe, push, light_leak, zoom, slide_left.
- End card: kicker, name, price, then a two-column grid (label over value).

## poster

Centred poster. Type is split above and below the photo.

- Cover: centred gold block, centred serif name, centred price with the unit always underneath, then the photo, then centred gold blocks.
- Title cards: centred gold block and centred title above the photo; captions only below the photo. No overlap.
- Captions: filled gold rectangles, square corners, centred as a group. Not pills.
- Transitions (`punch`): whip, flash, zoom_blur, spin, light_leak.
- End card: everything centred — block, name, price, unit, then one centred fact line per row.

## ledger

Price-led cover and a left gold rail. The rail stops at the photo so the picture stays full width.

- Cover: rail, huge price first, unit under the price, community name under that, kicker, photo, then one gold strip of facts.
- Title cards: gold block and the room title on one row (title drops below the block when the row is too wide), photo, gold strip.
- Captions: a single gold strip under the photo, black bold type, middots, centred inside the strip.
- Transitions (`signal`): glitch, wipe, push, light_leak, zoom_blur.
- End card: rail, name on the left, price right-aligned under the name, each fact as a gold label block plus a value.

## Shared text rule

Every drawn string is measured with its stroke, shadow, and price glow. The box must sit inside `[60, 1020] × [60, 1860]`. A line stays on one row at the largest size that fits, down to its minimum (48 px, or 120 px for titles and the price). If it still does not fit, it wraps into even pieces so the last line is not a single character (时代中国 / 时代天韵, not a leftover 韵). A bounds pass records each box and prints `text bounds check: PASS, N boxes`. `--text-bounds strict` exits non-zero on a miss.
