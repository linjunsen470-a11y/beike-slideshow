#!/usr/bin/env python3
"""Black-field real-estate e-brochure, 1080×1920. Pillow frames + ffmpeg H.264.

Full-bleed photo bands, pure black voids. One text grid (x=72, 8px snaps).
v4d 花字 system: solid gold tag block / huge Serif Black title with gradient fill,
dark outline and soft shadow / gold-gradient price / bold gold-outline fact chips.
No footer, no page numbers. Type scale 50/60/136/220 only; spacing 24/40/64.
v8: 15–20s pace, visible transitions (no hard cut, no shake), phrase-synced
soft BGM, beat-pulse off, each photo file used in at most one shot.
Cover is fully visible at frame 0 (no fade from black).
v10: --template gold_classic|editorial|poster|ledger|random. Text boxes,
stroke and shadow included, stay inside a 60px safe margin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import subprocess
from pathlib import Path

import numpy as np

import bgm_tools
import sfx_tools
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1920
BLACK = '#000000'
INK = '#F2EDE4'      # warm off-white, chip text / values
GREY = '#A39C92'     # secondary text (still bold, still >= 34px)
GOLD = '#B58A54'     # single accent
GOLD_HI = '#F3D9A8'  # champagne highlight (gradient top)
GOLD_LO = '#7A5A30'  # deep bronze (gradient bottom)
STROKE = '#0E0A06'   # 花字 outline
HAIR = '#3A352F'     # hairline dividers on black
# Back-compat aliases.
MUTED = GREY
DIM = GREY
RULE = GOLD

FONT_DIR = Path(__file__).resolve().parent / 'fonts'
SERIF_PATH = '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc'
SANS_PATH = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
SANS_BOLD_PATH = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
# Black (heaviest) weights are used when present (official Noto CJK SC Black, OFL),
# otherwise everything falls back to the installed Bold faces. Never Regular/Light.
SERIF_BLACK_PATH = FONT_DIR / 'NotoSerifCJKsc-Black.otf'
SANS_BLACK_PATH = FONT_DIR / 'NotoSansCJKsc-Black.otf'
DEFAULT_BGM = Path(__file__).resolve().parent / 'bgm/soft_ambient_28s.m4a'   # legacy
BGM_LIBRARY = Path(__file__).resolve().parent / 'bgm/library'   # royalty-free, see library.json
BGM_USER = Path(__file__).resolve().parent / 'bgm/user'         # drop your own licensed tracks here
# Library auto-pick stays on the softer phrase tracks. Summer Dream is still
# selectable with --bgm-track, but it is not the default.
SOFT_BGM = ('drawing-the-sky', 'happy-times')

# ---- Grid -----------------------------------------------------------------
# Every text line starts at MX; photos always run x=0..W. Positions snap to 8px.
# Each plate is one composition (tag / title / photo / chips) centred vertically.
MX = 72
BASE = 8
SAFE_TOP = 168
SAFE_BOTTOM = 300
GAP = 8                 # black gap between collage tiles
# v7: frame 0 is a finished cover. The old 0.4s fade-up from black is not applied.

# Ken Burns moves: (zoom start, zoom end, centre-x start, end, centre-y start, end).
# Zoom values are for strength 0.08 and scale linearly with --kb-strength; centre
# offsets are fractions of the slack the zoom creates inside the band.
KB_MOVES = {
    'push_in':  (1.00, 1.08, 0.0, 0.0, 0.0, 0.0),
    'pull_out': (1.08, 1.00, 0.0, 0.0, 0.0, 0.0),
    'pan_lr':   (1.08, 1.08, -0.9, 0.9, 0.0, 0.0),
    'pan_rl':   (1.08, 1.08, 0.9, -0.9, 0.0, 0.0),
    'diag_in':  (1.03, 1.08, -0.6, 0.6, 0.5, -0.5),
}
# Canonical transition names. `auto` keeps the v6 rotation; `random` (default)
# draws from RANDOM_POOL with no immediate repeat. `shake` stays available only
# when named explicitly — it is not in the default pool (no camera shake).
TRANSITIONS = {
    'fade', 'slide_left', 'slide_right', 'slide_up', 'wipe', 'zoom', 'black', 'cut',
    'push', 'whip', 'zoom_blur', 'flash', 'glitch', 'light_leak', 'shake', 'spin',
}
RANDOM_POOL = [
    'whip', 'zoom_blur', 'flash', 'glitch', 'light_leak', 'spin',
    'push', 'wipe', 'zoom',
]
# Dissolve-family effects are judged by mid blend weight, not pixel diff.
DISSOLVE_KINDS = {'fade', 'zoom'}
# Per-effect length when --transitions random. All sit in 0.34–0.40s.
# Floors: whip/glitch/flash/leak/spin/zoom-blur >= 0.32; wipe/push >= 0.36.
# --transition-duration is a cap (default 0.40) and never turns one into a cut.
TRANSITION_SECONDS = {
    'whip': 0.36, 'zoom_blur': 0.36, 'flash': 0.34, 'glitch': 0.36,
    'light_leak': 0.38, 'shake': 0.32, 'spin': 0.38, 'push': 0.38,
    'wipe': 0.40, 'zoom': 0.36, 'fade': 0.36,
    'slide_left': 0.38, 'slide_right': 0.38, 'slide_up': 0.38,
    'black': 0.38, 'cut': 0.0,
}
TRANSITION_FLOOR = {
    'whip': 0.32, 'zoom_blur': 0.32, 'flash': 0.32, 'glitch': 0.32,
    'light_leak': 0.32, 'shake': 0.32, 'spin': 0.32, 'zoom': 0.32, 'fade': 0.32,
    'push': 0.36, 'wipe': 0.36,
    'slide_left': 0.36, 'slide_right': 0.36, 'slide_up': 0.36, 'black': 0.36,
}
TRANSITION_ALIASES = {
    'whip_pan': 'whip', 'zoom_punch': 'zoom_blur', 'radial': 'zoom_blur',
    'flash_white': 'flash', 'rgb_split': 'glitch', 'lightleak': 'light_leak',
    'leak': 'light_leak', 'camera_shake': 'shake', 'rotate': 'spin',
    'spin_blur': 'spin', 'soft_wipe': 'wipe', 'zoom_dissolve': 'zoom',
    'slide': 'push',
}

# Shot order by listing type. Edit this table; slots with no photos are skipped.
#   community     小区展示. First shot is the cover (小区名 + 金价花字 + chips).
#   floorplan     户型图
#   cover         封面. Best interior (客厅) as 精美主图, title + price.
#   living        客厅, then 阳台
#   kitchen_bath  厨房, then 卫生间 (after 客厅/阳台, before 卧室)
#   bedrooms      卧室 single, then collage when there is more than one
#   end           封底信息卡, always last
SHOT_ORDER = {
    'sale': ['community', 'floorplan', 'cover', 'living', 'kitchen_bath', 'bedrooms', 'end'],
    'new':  ['community', 'floorplan', 'cover', 'living', 'kitchen_bath', 'bedrooms', 'end'],
    'rent': ['community', 'cover', 'floorplan', 'living', 'kitchen_bath', 'bedrooms', 'end'],
}

# v8 pace: (planned seconds, minimum, maximum). Phrase sync may move a cut
# inside the band. Totals of a full sale reel land near 17s before snapping.
DUR_COMMUNITY = (1.95, 1.60, 2.00)   # 小区 / 封面-style opening
DUR_COVER = (1.90, 1.60, 2.00)
DUR_COLLAGE = (2.30, 2.00, 2.40)
DUR_FLOORPLAN = (2.10, 1.80, 2.20)
DUR_ROOM = (1.50, 1.20, 1.60)
DUR_END = (2.10, 1.80, 2.20)

# ---- Type scale: only these four sizes are used anywhere ------------------
S = 50                  # tags, chips, end-card labels
M = 60                  # unit price, end-card values
L = 136                 # every title (rooms, community name, end card)
XL = 220                # price
TAG_SIZE = S
CHIP_SIZE = S
UNIT_SIZE = M
TITLE_SIZE = L
COLLAGE_TITLE = L
HERO_TITLE = L
PRICE_SIZE = XL
META_SIZE = CHIP_SIZE   # kept for older callers
COLLAGE_META = CHIP_SIZE

# ---- Spacing tokens -------------------------------------------------------
SP_S, SP_M, SP_L = 24, 40, 64
PILL_PAD_Y = 16         # tag and chip share this, so both are the same height
TAG_GAP = SP_M          # tag bottom -> title ink top
TITLE_OVERLAP = SP_M    # title ink straddles the photo top by exactly this
CHIP_GAP = SP_M         # photo bottom -> chip row
END_ROW_H = 120

COLLAGE_LEAD_H = 592    # 1080x592 lead + 8 + 536x400 pair = 1000
COLLAGE_PAIR_H = 400

TAGS = {'客厅': '客厅实拍', '卧室': '卧室空间', '卫生间': '卫浴空间', '阳台': '生活阳台',
        '厨房': '厨房', '户型': '户型格局', '小区': '小区环境', '房源': '房源信息'}


def canonical_transition(name):
    key = str(name).strip().lower().replace('-', '_').replace(' ', '_')
    return TRANSITION_ALIASES.get(key, key)


def stable_seed(listing_id, override):
    if override is not None and str(override) != '':
        return int(override)
    digest = hashlib.md5(str(listing_id or 'listing').encode()).hexdigest()
    return int(digest[:8], 16)


def _truthy_flag(value):
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', '是', '新房'}


def resolve_listing_type(listing, requested='auto'):
    """auto: new-home flag → new; rent price / 租 → rent; otherwise sale."""
    requested = (requested or 'auto').strip().lower()
    if requested in SHOT_ORDER:
        return requested
    if requested != 'auto':
        raise ValueError(f'Unknown --listing-type {requested}; choose auto, sale, new, rent')
    basic = listing.get('house_basic') or {}
    explicit = ' '.join(str(listing.get(k) or '') for k in (
        'listing_type', 'house_type', 'trade_type', 'deal_type')).strip().lower()
    if explicit in {'new', 'new_house', '新房'}:
        return 'new'
    if explicit in {'rent', 'lease', '租房', '出租'}:
        return 'rent'
    if explicit in {'sale', '二手', '售', '出售'}:
        return 'sale'
    flags = (listing.get('is_new'), listing.get('new_home'), listing.get('is_new_house'),
             basic.get('是否新房'), basic.get('新房'))
    if any(_truthy_flag(v) for v in flags if v not in (None, '', False, 0)):
        return 'new'
    if listing.get('rent_price') or listing.get('monthly_rent') or basic.get('租金'):
        return 'rent'
    price = str(listing.get('price') or basic.get('总价') or '')
    status = str(listing.get('status') or '')
    title = str(listing.get('title') or '')
    sale_state = str(basic.get('房源售卖状态') or '')
    if re.search(r'元\s*/\s*月', price) or re.search(r'整租|合租|出租', status + title + sale_state):
        return 'rent'
    if '租' in status and '售' not in status:
        return 'rent'
    if '新房' in status or '新房' in title or '新房' in sale_state:
        return 'new'
    return 'sale'


def shot_label(shot):
    slot = shot.get('slot')
    kind = shot.get('kind')
    title = shot.get('title') or ''
    if slot == 'community' and shot.get('hero'):
        return '小区展示'
    if slot == 'community':
        return '小区展示·拼贴'
    if slot == 'floorplan':
        return '户型图'
    if slot == 'cover':
        return '封面'
    if slot == 'living':
        return title or '客厅'
    if slot == 'kitchen_bath':
        return title or '厨卫'
    if slot == 'bedrooms' and kind == 'collage':
        return '卧室·拼贴'
    if slot == 'bedrooms':
        return '卧室'
    if slot == 'end':
        return '封底'
    return title or slot or kind


def slot_sequence(shots):
    seq = []
    for shot in shots:
        slot = shot.get('slot')
        if not seq or seq[-1] != slot:
            seq.append(slot)
    return seq


def snap(v):
    return int(round(v / BASE) * BASE)


def sc_index(path):
    """Face index for Simplified Chinese inside a Noto CJK collection."""
    for i in range(16):
        try:
            name = ImageFont.truetype(str(path), 20, index=i).getname()[0]
        except OSError:
            break
        if 'CJK SC' in name and 'Mono' not in name:
            return i
    return 0


def dot_join(parts):
    return ' · '.join(str(p) for p in parts if p)


def has_tag(tags, tag):
    return tag in [t.strip() for t in str(tags or '').split('/')]


def hex_rgb(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def vgradient(width, height, stops):
    """Vertical gradient image from [(pos 0..1, '#rrggbb'), ...]."""
    stops = [(p, hex_rgb(c)) for p, c in stops]
    column = Image.new('RGB', (1, max(1, height)))
    px = column.load()
    for y in range(height):
        t = y / max(1, height - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                k = (t - p0) / max(1e-6, p1 - p0)
                px[0, y] = tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))
                break
    return column.resize((max(1, width), max(1, height)))


GOLD_STOPS = [(0.0, GOLD_HI), (0.45, '#D9B47A'), (0.7, GOLD), (1.0, GOLD_LO)]
WHITE_STOPS = [(0.0, '#FFFFFF'), (0.6, '#F4EFE6'), (1.0, '#D9D0C2')]

# Text, stroke and shadow included, stays inside this inset. Titles and the
# price numerals never shrink below MIN_TITLE; every other string stays >= MIN_TEXT.
SAFE = 60
MIN_TEXT = 48
MIN_TITLE = 120
INK_THR = 16

# Visual presets. Shot order, timing, BGM and the photo rules do not change.
# Each entry differs in cover, title card, caption, transition family and end card.
TEMPLATE_ORDER = ('gold_classic', 'editorial', 'poster', 'ledger')
TEMPLATES = {
    'gold_classic': {
        'transitions': ('whip', 'zoom_blur', 'flash', 'glitch', 'light_leak', 'spin', 'push', 'wipe', 'zoom'),
    },
    'editorial': {
        'transitions': ('wipe', 'push', 'light_leak', 'zoom', 'slide_left'),
    },
    'poster': {
        'transitions': ('whip', 'flash', 'zoom_blur', 'spin', 'light_leak'),
    },
    'ledger': {
        'transitions': ('glitch', 'wipe', 'push', 'light_leak', 'zoom_blur'),
    },
}


def resolve_template_name(requested, seed, listing_id):
    """Return (template, seed). `random` picks from TEMPLATE_ORDER with `seed`."""
    requested = str(requested or 'gold_classic').strip().lower().replace('-', '_')
    if requested not in TEMPLATES and requested != 'random':
        names = ', '.join(TEMPLATE_ORDER)
        raise ValueError(f'Unknown --template {requested}; choose {names} or random')
    resolved = stable_seed(listing_id, seed)
    if requested == 'random':
        requested = random.Random(resolved).choice(TEMPLATE_ORDER)
    return requested, resolved


def load_assets(manifest, media):
    groups = {}
    for entry in manifest.get('ordered_images', []):
        name = Path(entry.get('path') or entry.get('rel_path') or '').name
        path = media / name
        if not path.is_file():
            path = Path(entry.get('path', ''))
        if not path.is_file():
            print(f'Skip missing: {name}', flush=True)
            continue
        role = entry.get('role', '')
        if role == 'vr_cover':
            continue
        key = role if role in ('community', 'floorplan') else entry.get('room', '')
        image = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
        groups.setdefault(key, []).append((name, image))
    return groups


def _ease(p, k=2.05):
    p = min(1.0, max(0.0, float(p)))
    if p < 0.5:
        return 0.5 * ((p * 2) ** k)
    return 1 - 0.5 * ((2 - 2 * p) ** k)


def _u8(arr):
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGB')


def _f32(img):
    if isinstance(img, np.ndarray):
        return img.astype(np.float32, copy=False)
    return np.asarray(img, dtype=np.float32)


def _box_blur(arr, radius, axis):
    """Separable box blur along width (axis=1) or height (axis=0)."""
    r = int(radius)
    if r < 1:
        return arr
    if axis == 1:
        pad = np.pad(arr, ((0, 0), (r, r), (0, 0)), mode='edge')
        c = np.cumsum(pad, axis=1, dtype=np.float32)
        c = np.concatenate([np.zeros((c.shape[0], 1, c.shape[2]), np.float32), c], axis=1)
    else:
        pad = np.pad(arr, ((r, r), (0, 0), (0, 0)), mode='edge')
        c = np.cumsum(pad, axis=0, dtype=np.float32)
        c = np.concatenate([np.zeros((1, c.shape[1], c.shape[2]), np.float32), c], axis=0)
    k = 2 * r + 1
    if axis == 1:
        return (c[:, k:, :] - c[:, :-k, :]) / k
    return (c[k:, :, :] - c[:-k, :, :]) / k


def _shift_edge(arr, dx, dy):
    if dx == 0 and dy == 0:
        return arr
    h, w = arr.shape[:2]
    pad_y, pad_x = abs(int(dy)) + 1, abs(int(dx)) + 1
    padded = np.pad(arr, ((pad_y, pad_y), (pad_x, pad_x), (0, 0)), mode='edge')
    y0 = pad_y - int(dy)
    x0 = pad_x - int(dx)
    return padded[y0:y0 + h, x0:x0 + w]


def _whip_slide(a, b, e, vertical, sign, blur):
    axis = 0 if vertical else 1
    aa = _box_blur(_f32(a), blur, axis)
    bb = _box_blur(_f32(b), blur, axis)
    if not vertical:
        shift = max(0, min(W, int(round(e * W))))
        if shift <= 0:
            return aa
        if shift >= W:
            return bb
        out = np.empty_like(aa)
        if sign < 0:          # A exits left, B enters from the right
            out[:, :W - shift] = aa[:, shift:]
            out[:, W - shift:] = bb[:, :shift]
        else:
            out[:, shift:] = aa[:, :W - shift]
            out[:, :shift] = bb[:, W - shift:]
        return out
    shift = max(0, min(H, int(round(e * H))))
    if shift <= 0:
        return aa
    if shift >= H:
        return bb
    out = np.empty_like(aa)
    if sign < 0:              # A exits up
        out[:H - shift] = aa[shift:]
        out[H - shift:] = bb[:shift]
    else:
        out[shift:] = aa[:H - shift]
        out[:shift] = bb[H - shift:]
    return out


def _zoom_blur(img, amount, samples=6):
    if amount < 0.02:
        return _f32(img)
    acc = np.zeros((H, W, 3), np.float32)
    src = img if isinstance(img, Image.Image) else _u8(img)
    for i in range(samples):
        z = 1.0 + amount * 1.05 * (i / (samples - 1))
        cw, ch = W / z, H / z
        box = ((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2)
        scaled = src.resize((W, H), Image.Resampling.BILINEAR, box=box)
        acc += np.asarray(scaled, np.float32)
    return acc / samples


def _spin_frame(img, angle, spread):
    """Rotate with a little angular blur. Scale just enough to hide black corners."""
    reach = abs(angle) + abs(spread)
    if reach < 0.35:
        return _f32(img)
    th = reach * math.pi / 180.0
    # Cover scale of the furthest blurred sample, plus a hair of margin.
    scale = (abs(math.cos(th)) + abs(math.sin(th)) * (H / float(W))) * 1.08
    scale = max(1.0, scale)
    samples = (0.0,) if spread < 0.8 else (-spread, 0.0, spread)
    acc = np.zeros((H, W, 3), np.float32)
    for d in samples:
        rot = img.rotate(angle + d, resample=Image.Resampling.BILINEAR, fillcolor=(0, 0, 0))
        if scale > 1.004:
            cw, ch = W / scale, H / scale
            box = ((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2)
            rot = rot.resize((W, H), Image.Resampling.BILINEAR, box=box)
        acc += np.asarray(rot, np.float32)
    return acc / len(samples)


class Magazine:
    def __init__(self, listing, groups, serif_path, cta='', kenburns=True, kb_strength=0.08,
                 transitions='random', transition_dur=0.40, listing_type='auto', seed=None,
                 beat_pulse=False, fps=30, template='gold_classic'):
        self.data = listing
        self.groups = groups
        self.cta = (cta or '').strip()
        self.fonts = {}
        self.cache = {}
        self.plates = {}
        self.text_boxes = []
        self._capture = False
        if template not in TEMPLATES:
            raise ValueError(f'Unknown template {template}; choose {", ".join(TEMPLATE_ORDER)}')
        self.template_name = template
        self.transition_pool = tuple(TEMPLATES[template]['transitions'])
        # --font overrides the title face; otherwise prefer Serif Black when installed.
        if str(serif_path) == SERIF_PATH and SERIF_BLACK_PATH.is_file():
            serif_path = str(SERIF_BLACK_PATH)
        self.serif_path = str(serif_path)
        self.serif_index = sc_index(self.serif_path)
        self.sans_path = str(SANS_BLACK_PATH) if SANS_BLACK_PATH.is_file() else SANS_BOLD_PATH
        self.sans_index = sc_index(self.sans_path)
        self.sans_bold_index = sc_index(SANS_BOLD_PATH)
        self.black = Image.new('RGB', (W, H), BLACK)

        basic = listing.get('house_basic') or {}
        resblock = listing.get('resblock_basic') or {}
        layout = str(listing.get('layout') or '')
        self.layout_full = layout
        self.layout_short = ''.join(re.findall(r'\d+[室厅]', layout)) or layout
        rooms = re.search(r'(\d+)室', layout)
        self.bedroom_count = int(rooms.group(1)) if rooms else 0
        self.area = str(listing.get('area_sqm') or '')
        self.inner_area = str(listing.get('inner_area_sqm') or basic.get('套内面积') or '')
        self.efficiency = re.sub(r'\.0+%$', '%', str(basic.get('得房率') or ''))
        self.price = str(listing.get('price') or '')
        self.unit = str(listing.get('unit_price') or '').replace('平米', '㎡')
        self.community = str(listing.get('community') or '')
        self.city = str(listing.get('city') or '')
        self.district = str(listing.get('district') or '')
        self.bizcircle = str(listing.get('bizcircle') or '')
        self.place = dot_join([self.district, self.bizcircle])
        self.year = str(listing.get('built_year') or '')
        self.structure = str(basic.get('户型结构') or '')
        self.green = str(resblock.get('绿化率') or '')
        self.households = resblock.get('总户数')
        self.tags = str(listing.get('tags') or '')
        ori = str(listing.get('orientation') or '')
        if ori in {'东', '南', '西', '北', '东南', '东北', '西南', '西北'}:
            ori = '朝' + ori
        self.orientation = ori
        self.floor = str(listing.get('floor') or '')
        self.total_floors = str(listing.get('total_floors') or '')
        self.decoration = str(listing.get('decoration') or '')
        self.specs = dot_join([ori, self.floor, self.decoration])
        self.listing_type = resolve_listing_type(listing, listing_type)
        self.seed = stable_seed(listing.get('listing_id'), seed)
        self.beat_pulse = bool(beat_pulse)
        self.fps = int(fps) if int(fps) > 0 else 30
        self.strong_beats = []
        self.downbeats = []
        self.phrase_onsets = []
        self.phrase_offset = 0.0
        self.beat_times = []
        self.beat_deltas = []
        self.phrase_snaps = []
        self.used_files = set()
        self.skipped = []
        self.shots, self.sections = self._timeline()
        self.total_sections = len(self.sections)
        self.duration = sum(shot['dur'] for shot in self.shots)
        self.kenburns = bool(kenburns)
        self.kb_strength = float(kb_strength)
        self.assign_motion(transitions, transition_dur)

    def _loc_tag(self):
        return '·'.join(p for p in (self.city, self.district, self.bizcircle) if p) or TAGS['房源']

    def _cover_meta(self):
        return [p for p in (self.layout_short, self.area, self.orientation, self.decoration) if p]

    def _best_interior(self):
        """精美主图: 客厅, then the first other interior we have."""
        for key in ('客厅', '卧室', '阳台', '厨房', '卫生间'):
            if self.groups.get(key):
                return self.groups[key][0]
        return None

    def _room_facts(self, key):
        if key == '客厅':
            names = ('客厅朝南', '客厅带阳台', '带落地窗')
        elif key == '阳台':
            names = ('客厅带阳台', '带阳台')
        elif key == '卫生间':
            names = ('卫生间带窗',)
        elif key == '厨房':
            names = ('厨房带窗', '厨房带阳台')
        elif key == '卧室':
            names = ('主卧朝南', '带飘窗')
        else:
            names = ()
        facts = [t for t in names if has_tag(self.tags, t)]
        if key == '卧室' and self.bedroom_count:
            facts.insert(0, f'{self.bedroom_count}间卧室')
        return facts

    def _skip(self, message):
        self.skipped.append(message)
        print(f'Skip duplicate: {message}', flush=True)

    def _claim_one(self, items, where):
        """First image in `items` whose file is not already on screen."""
        items = [item for item in (items or []) if item]
        for item in items:
            name = item[0]
            if name not in self.used_files:
                self.used_files.add(name)
                return item
        if items:
            names = ', '.join(item[0] for item in items)
            self._skip(f'{where}: no unused image (already shown: {names})')
        return None

    def _claim_many(self, items, count, where):
        """Up to `count` unused files. Already-shown files are logged and skipped."""
        picked = []
        for item in items or []:
            name = item[0]
            if name in self.used_files:
                self._skip(f'{name} already shown, excluded from {where}')
                continue
            self.used_files.add(name)
            picked.append(item)
            if len(picked) >= count:
                break
        return picked

    def _timed(self, shot, spec):
        default, lo, hi = spec
        shot['dur'] = float(default)
        shot['dur_plan'] = float(default)
        shot['dur_lo'] = float(lo)
        shot['dur_hi'] = float(hi)
        if shot.get('photo') is not None and not shot.get('files'):
            shot['files'] = [shot['photo'][0]]
        if shot.get('photos') is not None:
            shot['files'] = [item[0] for item in shot['photos']]
        shot.setdefault('files', [])
        return shot

    def _room_band(self, key, photo, plate):
        return self._timed(dict(
            kind='band', label=key, title=key, tag=TAGS.get(key, key),
            photo=photo, meta=self._room_facts(key), plate=plate, files=[photo[0]],
        ), DUR_ROOM)

    def _shots_community(self):
        community = list(self.groups.get('community') or [])
        if not community:
            return []
        # Manifest order is the curated pick. With three or more, the opening
        # full-bleed is the third frame; the collage uses other files only.
        if len(community) >= 3:
            order = [community[2], community[1], community[0]] + community[3:]
        else:
            order = community
        seen, ordered = set(), []
        for item in order:
            if item[0] not in seen:
                ordered.append(item)
                seen.add(item[0])
        hero = self._claim_one(ordered, '小区展示')
        if hero is None:
            return []
        comm_meta = [m for m in (
            f'{self.year}建成' if self.year else '',
            f'绿化率{self.green}' if self.green else '',
            f'{self.households}户' if self.households else '',
        ) if m]
        opening = self._timed(dict(
            kind='band', label='小区', hero=True, title=self.community, tag=self._loc_tag(),
            photo=hero, meta=self._cover_meta(), plate='com_single', files=[hero[0]],
        ), DUR_COMMUNITY)
        if len(community) < 3:
            return [opening]
        tiles = self._claim_many(ordered, 3, '小区拼贴')
        if len(tiles) < 2:
            print(f'Skip shot: 小区拼贴 needs 2 unused photos, found {len(tiles)}', flush=True)
            return [opening]
        collage = self._timed(dict(
            kind='collage', label='小区', title=self.community, tag=TAGS['小区'],
            photos=tiles, meta=comm_meta, plate='com_collage',
        ), DUR_COLLAGE)
        return [opening, collage]

    def _shots_floorplan(self):
        photo = self._claim_one(self.groups.get('floorplan'), '户型图')
        if photo is None:
            return []
        meta = [f'建面{self.area}' if self.area else '']
        if self.inner_area:
            meta.append(f'套内{self.inner_area}')
        if self.efficiency:
            meta.append(f'得房率{self.efficiency}')
        elif self.structure:
            meta.append(self.structure)
        meta = [m for m in meta if m]
        return [self._timed(dict(
            kind='band', label='户型', title=self.layout_full or '户型', tag=TAGS['户型'],
            photo=photo, meta=meta, overlap=0, plate='floorplan', files=[photo[0]],
        ), DUR_FLOORPLAN)]

    def _shots_cover(self):
        pool = []
        for key in ('客厅', '卧室', '阳台', '厨房', '卫生间'):
            pool += self.groups.get(key) or []
        photo = self._claim_one(pool, '封面')
        if photo is None:
            return []
        return [self._timed(dict(
            kind='band', label='封面', hero=True, title=self.community, tag=self._loc_tag(),
            photo=photo, meta=self._cover_meta(), plate='cover', files=[photo[0]],
        ), DUR_COVER)]

    def _shots_living(self):
        plates = {'客厅': 'living', '阳台': 'balcony'}
        shots = []
        for key in ('客厅', '阳台'):
            photo = self._claim_one(self.groups.get(key), key)
            if photo is None:
                continue
            shots.append(self._room_band(key, photo, plates[key]))
        return shots

    def _shots_kitchen_bath(self):
        plates = {'厨房': 'kitchen', '卫生间': 'bath'}
        shots = []
        for key in ('厨房', '卫生间'):
            photo = self._claim_one(self.groups.get(key), key)
            if photo is None:
                continue
            shots.append(self._room_band(key, photo, plates[key]))
        return shots

    def _shots_bedrooms(self):
        beds = list(self.groups.get('卧室') or [])
        photo = self._claim_one(beds, '卧室')
        if photo is None:
            return []
        facts = self._room_facts('卧室')
        band = self._timed(dict(
            kind='band', label='卧室', title='卧室', tag=TAGS['卧室'], photo=photo,
            meta=facts, plate='bed_single', files=[photo[0]],
        ), DUR_ROOM)
        items = [band]
        rest = self._claim_many(beds, 3, '卧室拼贴')
        if len(rest) >= 2:
            items.append(self._timed(dict(
                kind='collage', label='卧室', title='卧室', tag=TAGS['卧室'],
                photos=rest, meta=facts, plate='bed_collage',
            ), DUR_COLLAGE))
        elif len(rest) == 1:
            # A second angle is its own full-bleed, not a one-tile collage of a repeat.
            items.append(self._room_band('卧室', rest[0], 'bed_single_b'))
        return items

    def _shots_end(self):
        return [self._timed(dict(
            kind='end', plate='end', label='封底', title=self.community, files=[],
        ), DUR_END)]

    def _slot_items(self, slot):
        return {
            'community': self._shots_community,
            'floorplan': self._shots_floorplan,
            'cover': self._shots_cover,
            'living': self._shots_living,
            'kitchen_bath': self._shots_kitchen_bath,
            'bedrooms': self._shots_bedrooms,
            'end': self._shots_end,
        }[slot]()

    def _timeline(self):
        """Build shots in SHOT_ORDER[listing_type]. The table is the only ordering."""
        shots, sections = [], []
        number = 1
        for slot in SHOT_ORDER[self.listing_type]:
            items = self._slot_items(slot)
            if not items:
                continue
            index = f'{number:02d}'
            number += 1
            start = sum(s['dur'] for s in shots)
            for item in items:
                item['index'] = index
                item['slot'] = slot
                shots.append(item)
            sections.append({'template': slot, 'start': start,
                             'duration': sum(s['dur'] for s in items)})
        seen = []
        for shot in shots:
            for name in shot.get('files') or []:
                if name in seen:
                    raise RuntimeError(f'duplicate photo across shots: {name}')
                seen.append(name)
        return shots, sections

    # ---- type primitives -------------------------------------------------
    def font(self, kind, size):
        """'serif' = title face (Black if installed); anything else = Sans Black/Bold."""
        key = (kind, size)
        if key not in self.fonts:
            if kind == 'serif':
                path, index = self.serif_path, self.serif_index
            elif kind == 'sansBold':
                path, index = SANS_BOLD_PATH, self.sans_bold_index
            else:
                path, index = self.sans_path, self.sans_index
            self.fonts[key] = ImageFont.truetype(path, size, index=index)
        return self.fonts[key]

    def text_width(self, text, kind, size, tracking=0):
        if not text:
            return 0
        font = self.font(kind, size)
        if tracking == 0:
            return font.getlength(text)
        return sum(font.getlength(ch) for ch in text) + tracking * (len(text) - 1)

    def fit(self, text, kind, size, max_w, tracking=0, minimum=None):
        if minimum is None:
            minimum = MIN_TEXT
        while size > minimum and self.text_width(text, kind, size, tracking) > max_w:
            size -= 2
        return size

    def ink(self, text, kind, size):
        """(top, bottom) of the ink relative to the baseline (top negative)."""
        if not text:
            return 0, 0
        box = self.font(kind, size).getbbox(text, anchor='ls')
        return box[1], box[3]

    def draw(self, draw, xy, text, kind, size, fill, tracking=0, anchor='ls', record=True, role='text'):
        """Plain text at a baseline. Returns the x after the last glyph."""
        if not text:
            return xy[0]
        font = self.font(kind, size)
        x, y = xy
        if record and anchor == 'ls':
            if tracking == 0:
                rel = self.rel_box(text, kind, size, 0, (0, 0), 0, glow=False)
                self._note((x + rel[0], y + rel[1], x + rel[2], y + rel[3]), text, role, size)
            else:
                width = self.text_width(text, kind, size, tracking)
                top, bot = self.ink(text, kind, size)
                self._note((x, y + top, x + width, y + bot), text, role, size)
        if tracking == 0:
            draw.text((x, y), text, font=font, fill=fill, anchor=anchor)
            return x + font.getlength(text)
        for ch in text:
            draw.text((x, y), ch, font=font, fill=fill, anchor=anchor)
            x += font.getlength(ch) + tracking
        return x - tracking

    def fancy(self, image, xy, text, kind, size, stops, stroke=4, shadow=(0, 8), blur=10, glow=False,
              role='title'):
        """花字: gradient fill + dark outline + soft drop shadow, drawn at a baseline.

        Returns the x after the last glyph.
        """
        if not text:
            return xy[0]
        font = self.font(kind, size)
        x, y = xy
        rel = self.rel_box(text, kind, size, stroke, shadow, blur, glow=glow)
        self._note((x + rel[0], y + rel[1], x + rel[2], y + rel[3]), text, role, size)
        pad = stroke + blur * 3 + max(abs(shadow[0]), abs(shadow[1]))
        left, top, right, bottom = font.getbbox(text, anchor='ls', stroke_width=stroke)
        w, h = right - left + pad * 2, bottom - top + pad * 2
        ox, oy = pad - left, pad - top          # baseline origin inside the patch
        fill_mask = Image.new('L', (w, h), 0)
        ImageDraw.Draw(fill_mask).text((ox, oy), text, font=font, fill=255, anchor='ls')
        outline = Image.new('L', (w, h), 0)
        ImageDraw.Draw(outline).text((ox, oy), text, font=font, fill=255, anchor='ls',
                                     stroke_width=stroke, stroke_fill=255)
        px, py = int(x - ox), int(y - oy)
        # Soft shadow (and optional warm glow) under the letterforms.
        shade = outline.filter(ImageFilter.GaussianBlur(blur))
        shade = shade.point(lambda v: int(v * 0.85))
        image.paste(Image.new('RGB', (w, h), '#000000'), (px + shadow[0], py + shadow[1]), shade)
        if glow:
            halo = outline.filter(ImageFilter.GaussianBlur(blur * 2)).point(lambda v: int(v * 0.35))
            image.paste(Image.new('RGB', (w, h), GOLD), (px, py), halo)
        image.paste(Image.new('RGB', (w, h), STROKE), (px, py), outline)
        ink_top, ink_bottom = oy + font.getbbox(text, anchor='ls')[1], oy + font.getbbox(text, anchor='ls')[3]
        grad = Image.new('RGB', (w, h), BLACK)
        grad.paste(vgradient(w, ink_bottom - ink_top, stops), (0, ink_top))
        image.paste(grad, (px, py), fill_mask)
        return x + font.getlength(text)

    def pill_height(self, size=S):
        t, b = self.ink('国8', 'sans', size)
        return (b - t) + PILL_PAD_Y * 2

    def tag(self, draw, x, top, text, size=TAG_SIZE, fill=GOLD, ink='#0A0704'):
        """Solid gold label block with black bold text. Returns (right, bottom).

        Same height as a chip, so tag and chips read as one family.
        """
        if not text:
            return x, top
        pad_x = 28
        size = int(size)
        while size > MIN_TEXT:
            width = self.text_width(text, 'sans', size, tracking=2) + pad_x * 2
            if x + width <= W - SAFE:
                break
            size -= 2
        width = self.text_width(text, 'sans', size, tracking=2) + pad_x * 2
        height = self.pill_height(size)
        if x < SAFE:
            x = SAFE
        rect = (int(x), int(top), int(x + width), int(top + height))
        draw.rounded_rectangle(rect, radius=12, fill=fill)
        self._note(rect, text, 'tag', size)
        t, _ = self.ink('国8', 'sans', size)
        self.draw(draw, (x + pad_x, top + PILL_PAD_Y - t), text, 'sans', size, ink,
                  tracking=2, record=False)
        return x + width, top + height

    def chip_rows(self, parts, size=CHIP_SIZE, x0=MX, right=None):
        """Greedy wrap of chips into rows: [[(text, x, width), ...], ...]."""
        pad_x = 28
        if right is None:
            right = W - SAFE - 4
        x0 = max(SAFE, x0)
        rows, row, x = [], [], x0
        for part in [p for p in parts if p]:
            width = self.text_width(part, 'sans', size) + pad_x * 2
            if row and x + width > right:
                rows.append(row)
                row, x = [], x0
            row.append((part, x, width))
            x += width + SP_S
        if row:
            rows.append(row)
        return rows

    def chips_height(self, parts, size=CHIP_SIZE):
        rows = self.chip_rows(parts, size)
        if not rows:
            return 0
        # The drawn outline sits 2px outside the pill rect on every side.
        # Reserve that so the recorded box stays inside the 60px safe area.
        return len(rows) * self.pill_height(size) + (len(rows) - 1) * SP_S + 4

    def chips(self, draw, top, parts, size=CHIP_SIZE, first_filled=False):
        """Bold pill chips, gold outline, left-aligned rows. Returns bottom."""
        rows = self.chip_rows(parts, size)
        if not rows:
            return top
        t, _ = self.ink('国8', 'sans', size)
        height = self.pill_height(size)
        y = top
        first = True
        pad = 2  # outline width 3 is centred on the edge
        for row in rows:
            for text, x, width in row:
                filled = first_filled and first
                first = False
                rect = (int(x), int(y), int(x + width), int(y + height))
                draw.rounded_rectangle(rect, radius=height // 2,
                                       fill=GOLD if filled else BLACK, outline=GOLD, width=3)
                self._note((rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad),
                           text, 'caption', size)
                self.draw(draw, (x + 28, y + PILL_PAD_Y - t), text, 'sans', size,
                          '#0A0704' if filled else INK, record=False)
            y += height + SP_S
        return y - SP_S

    def resize_w(self, photo, width):
        key = (id(photo), width)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        pw, ph = photo.size
        height = max(2, round(ph * width / pw))
        image = photo.resize((width, height), Image.Resampling.LANCZOS)
        self.cache[key] = image
        return image

    def cover(self, photo, width, height):
        """Centre-crop to exactly width x height (collage tiles)."""
        key = (id(photo), width, height)
        hit = self.cache.get(key)
        if hit is None:
            hit = ImageOps.fit(photo, (width, height), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            self.cache[key] = hit
        return hit

    # ---- text measurement (stroke, shadow, glow) -------------------------
    def _vis_bbox(self, mask):
        return mask.point(lambda p: 255 if p >= INK_THR else 0).getbbox()

    def rel_box(self, text, kind, size, stroke=0, shadow=(0, 0), blur=0, glow=False):
        """Visible (left, top, right, bottom) relative to a baseline-left anchor.

        Includes the outline, the drop shadow and the optional price glow.
        The box is one pixel larger than the visible ink so a passing check
        is not a clipped glyph.
        """
        if not text:
            return (0, 0, 0, 0)
        key = ('relbox', kind, int(size), int(stroke), tuple(shadow), int(blur), bool(glow), text)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        font = self.font(kind, size)
        left, top, right, bottom = font.getbbox(text, anchor='ls', stroke_width=max(0, int(stroke)))
        extra = int(stroke) + int(blur) * 3 + max(abs(int(shadow[0])), abs(int(shadow[1])))
        extra += int(blur) * 2 if glow else 0
        extra += 8
        w = max(1, int(right - left + extra * 2))
        h = max(1, int(bottom - top + extra * 2))
        ox, oy = int(extra - left), int(extra - top)
        outline = Image.new('L', (w, h), 0)
        ImageDraw.Draw(outline).text((ox, oy), text, font=font, fill=255, anchor='ls',
                                     stroke_width=int(stroke), stroke_fill=255)
        boxes = []
        ob = self._vis_bbox(outline)
        if ob:
            boxes.append(ob)
        if blur or shadow != (0, 0):
            shade = outline.filter(ImageFilter.GaussianBlur(blur)) if blur else outline
            sb = self._vis_bbox(shade)
            if sb:
                boxes.append((sb[0] + shadow[0], sb[1] + shadow[1], sb[2] + shadow[0], sb[3] + shadow[1]))
        if glow and blur:
            halo = outline.filter(ImageFilter.GaussianBlur(blur * 2)).point(lambda v: int(v * 0.35))
            hb = self._vis_bbox(halo)
            if hb:
                boxes.append(hb)
        if not boxes:
            boxes.append((ox, oy, ox + 1, oy + 1))
        l = min(b[0] for b in boxes) - ox
        t = min(b[1] for b in boxes) - oy
        r = max(b[2] for b in boxes) - ox
        btm = max(b[3] for b in boxes) - oy
        hit = (int(math.floor(l)) - 1, int(math.floor(t)) - 1,
               int(math.ceil(r)) + 1, int(math.ceil(btm)) + 1)
        self.cache[key] = hit
        return hit

    def _note(self, box, text, role, size):
        if not self._capture or not text:
            return
        l, t, r, b = (int(math.floor(box[0])), int(math.floor(box[1])),
                      int(math.ceil(box[2])), int(math.ceil(box[3])))
        self.text_boxes.append({
            'text': str(text), 'role': role, 'size': int(size),
            'left': l, 'top': t, 'right': r, 'bottom': b,
        })

    def _center_x(self, rel):
        x = (W - (rel[2] - rel[0])) // 2 - rel[0]
        if x + rel[0] < SAFE:
            x = SAFE - rel[0]
        if x + rel[2] > W - SAFE:
            x = (W - SAFE) - rel[2]
        return int(x)

    def _right_x(self, rel, right=None):
        right = W - SAFE if right is None else right
        x = right - rel[2]
        if x + rel[0] < SAFE:
            x = SAFE - rel[0]
        return int(x)

    def _line_bases(self, lines, top, gap=12):
        """Baselines so each decorated box starts at `top` and then stacks."""
        bases = []
        y = top
        for _text, _x, rel in lines:
            base = y - rel[1]
            bases.append(base)
            y = base + rel[3] + gap
        bottom = (y - gap) if lines else top
        return bases, bottom

    def fit_lines(self, text, kind, preferred, minimum, max_right, prefer_x=MX,
                  stroke=0, shadow=(0, 0), blur=0, glow=False, max_lines=4):
        """Shrink, then wrap on a balanced split. Returns (size, [(line, x, rel), ...]).

        One line is kept at the largest size that fits. A title that cannot sit
        on one line, even at `minimum`, wraps into even pieces (时代中国 / 时代天韵)
        instead of filling the first line and leaving a single character.
        """
        text = (text or '').strip()
        if not text:
            return preferred, []
        preferred = int(preferred)
        minimum = int(minimum)
        n = len(text)

        def placed(s, size):
            rel = self.rel_box(s, kind, size, stroke, shadow, blur, glow=glow)
            x = max(prefer_x, SAFE - rel[0])
            return rel, int(x), (x + rel[2] <= max_right)

        size = preferred
        while size >= minimum:
            rel, x, ok = placed(text, size)
            if ok:
                return size, [(text, x, rel)]
            if size == minimum:
                break
            size -= 2

        def cheap_wide(s, size):
            # Only skip a raster when the advance is far past the content box.
            room = max_right - max(prefer_x, SAFE)
            extra = int(stroke) * 2 + int(blur) + abs(int(shadow[0])) + 24
            return self.text_width(s, kind, size) > room + extra

        def try_parts(parts, size):
            out = []
            for part in parts:
                if not part or cheap_wide(part, size):
                    return None
                rel, x, ok = placed(part, size)
                if not ok:
                    return None
                out.append((part, x, rel))
            return out

        def score(parts):
            lens = [len(p) for p in parts]
            orphan = sum(1 for length in lens if length <= 1)
            return (orphan, max(lens) - min(lens), -min(lens))

        def candidates(nlines):
            if n < nlines or nlines < 2:
                return []
            target = n / float(nlines)
            slack = 2 if n <= 16 else 1
            min_each = 2 if n >= nlines * 2 else 1
            lo = max(min_each, int(target) - slack)
            hi = max(lo, int(target) + slack)
            found = []

            def rec(start, left, acc):
                if len(found) > 64:
                    return
                if left == 1:
                    seg = text[start:]
                    if len(seg) < min_each:
                        return
                    if abs(len(seg) - target) > slack + 2:
                        return
                    found.append(acc + [seg])
                    return
                remain_lines = left - 1
                for length in range(lo, hi + 1):
                    nxt = start + length
                    if n - nxt < remain_lines * min_each:
                        break
                    rec(nxt, remain_lines, acc + [text[start:nxt]])

            rec(0, nlines, [])
            if n % nlines == 0:
                step = n // nlines
                even = [text[i:i + step] for i in range(0, n, step)]
                if even not in found and all(len(p) >= min_each for p in even):
                    found.append(even)
            # A separator is a better break than a mid-word cut when both exist.
            for sep in ('  ·  ', ' · ', '·', '    ', '  ', ' '):
                if sep not in text:
                    continue
                bits = [p for p in text.split(sep) if p]
                if 2 <= len(bits) <= max_lines:
                    found.insert(0, bits)
            found.sort(key=score)
            # Unique, best score first.
            uniq, seen = [], set()
            for parts in found:
                key = tuple(parts)
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(parts)
            return uniq

        size = preferred
        while size >= minimum:
            for nlines in range(2, int(max_lines) + 1):
                for parts in candidates(nlines):
                    packed = try_parts(parts, size)
                    if packed is not None:
                        return size, packed
            if size == minimum:
                break
            size -= 2

        # Nothing balanced fit. Greedy fill at the minimum size; the bounds
        # check reports a box that still leaves the safe area.
        size = minimum
        lines, cur = [], ''
        for ch in text:
            trial = cur + ch
            rel = self.rel_box(trial, kind, size, stroke, shadow, blur, glow=glow)
            x = max(prefer_x, SAFE - rel[0])
            if cur and x + rel[2] > max_right:
                rel_c = self.rel_box(cur, kind, size, stroke, shadow, blur, glow=glow)
                x_c = max(prefer_x, SAFE - rel_c[0])
                lines.append((cur, int(x_c), rel_c))
                cur = ch
            else:
                cur = trial
        if cur:
            rel_c = self.rel_box(cur, kind, size, stroke, shadow, blur, glow=glow)
            x_c = max(prefer_x, SAFE - rel_c[0])
            lines.append((cur, int(x_c), rel_c))
        return size, lines

    def plan_price(self, prefer_x=MX, max_right=None, force_stack=False, align='left',
                   price_size=PRICE_SIZE, unit_size=UNIT_SIZE):
        """Place the price and the unit inside the safe width.

        Inline when both fit at their preferred sizes. Otherwise the unit wraps
        under the price. A line shrinks only down to its minimum, then wraps.
        """
        max_right = W - SAFE if max_right is None else max_right
        price = self.price or '—'
        unit = (self.unit or '').strip()
        stroke, shadow, blur = 5, (0, 10), 12

        def place_x(rel):
            if align == 'center':
                return self._center_x(rel)
            if align == 'right':
                return self._right_x(rel, max_right)
            return int(max(prefer_x, SAFE - rel[0]))

        ps = int(price_size)
        while ps > MIN_TITLE:
            rel = self.rel_box(price, 'serif', ps, stroke, shadow, blur, glow=True)
            if place_x(rel) + rel[2] <= max_right and rel[2] - rel[0] <= (W - 2 * SAFE):
                break
            ps -= 2
        prel = self.rel_box(price, 'serif', ps, stroke, shadow, blur, glow=True)
        ax = place_x(prel)
        if ax + prel[2] > max_right:
            ax = max(SAFE - prel[0], max_right - prel[2])

        def finish(mode, us, ulines, ubases, ux=None, urel=None):
            below = prel[3]
            if mode == 'inline' and urel is not None:
                below = max(below, urel[3])
            elif mode == 'stack' and ulines:
                below = ubases[-1] + ulines[-1][2][3]
            return dict(mode=mode, price=price, unit=unit, price_size=ps, unit_size=us,
                        price_x=int(ax), price_rel=prel, unit_x=ux, unit_rel=urel,
                        unit_lines=ulines, unit_bases=ubases, above=prel[1], below=below)

        if unit and not force_stack and align == 'left':
            urel = self.rel_box(unit, 'sans', unit_size, 0, (0, 0), 0)
            ux = ax + int(self.text_width(price, 'serif', ps)) + SP_M
            if (ux + urel[0] >= SAFE and ux + urel[2] <= max_right
                    and ux >= ax + prel[2] - 4 and ax + prel[2] <= max_right):
                return finish('inline', unit_size, [], [], ux, urel)

        if not unit:
            return finish('solo', unit_size, [], [])

        us, wrapped = self.fit_lines(unit, 'sans', unit_size, MIN_TEXT, max_right, prefer_x=prefer_x)
        if align != 'left':
            wrapped = [(text, place_x(rel) if align == 'center' else self._right_x(rel, max_right), rel)
                       for text, _x, rel in wrapped]
            # right-align each unit line to the price's right edge when asked
            if align == 'right':
                wrapped = [(text, self._right_x(rel, ax + prel[2]), rel) for text, _x, rel in wrapped]
        gap = 18
        if wrapped:
            ubases = [prel[3] + gap - wrapped[0][2][1]]
            for i in range(1, len(wrapped)):
                prev, cur = wrapped[i - 1][2], wrapped[i][2]
                ubases.append(ubases[-1] + prev[3] + 10 - cur[1])
        else:
            ubases = []
        return finish('stack', us, wrapped, ubases)

    def paint_price_plan(self, image, plan, baseline, unit_fill=GREY):
        self.fancy(image, (plan['price_x'], baseline), plan['price'], 'serif', plan['price_size'],
                   GOLD_STOPS, stroke=5, shadow=(0, 10), blur=12, glow=True, role='price')
        if not plan.get('unit'):
            return plan
        draw = ImageDraw.Draw(image)
        if plan['mode'] == 'inline':
            self.draw(draw, (plan['unit_x'], baseline), plan['unit'], 'sans', plan['unit_size'],
                      unit_fill, role='unit')
        else:
            for (line, x, _rel), brel in zip(plan['unit_lines'], plan['unit_bases']):
                self.draw(draw, (x, baseline + brel), line, 'sans', plan['unit_size'],
                          unit_fill, role='unit')
        return plan

    def _contain(self, above, photo_h, below, prefer_min=SAFE):
        """Origin and photo box so above + photo + below sits in the safe frame."""
        natural = max(1, int(photo_h))
        block = above + natural + below
        floor, ceil = SAFE, H - SAFE
        origin = (H - block) // 2
        if origin < prefer_min:
            origin = prefer_min
        if origin < floor:
            origin = floor
        if origin + block > ceil:
            origin = max(floor, ceil - block)
        out_h, out_w, out_x = natural, W, 0
        if origin + above + natural + below > ceil:
            room = max(160, ceil - max(floor, origin) - above - below)
            out_h = min(natural, room)
            out_w = max(2, int(round(W * out_h / natural)))
            if out_w % 2:
                out_w -= 1
            out_w = max(2, min(W, out_w))
            out_x = (W - out_w) // 2
            origin = max(floor, min(origin, ceil - (above + out_h + below)))
        if prefer_min >= SAFE_TOP and origin + above + out_h + below <= ceil:
            snapped = snap(origin)
            if snapped >= floor and snapped + above + out_h + below <= ceil:
                origin = snapped
        return int(origin), int(out_h), int(out_w), int(out_x)

    # ---- composed elements -----------------------------------------------
    def paint_title(self, image, base, title, size):
        self.fancy(image, (MX, base), title, 'serif', size, WHITE_STOPS, stroke=4, shadow=(0, 8), blur=10)

    def price_lockup(self, image, x, base, size=PRICE_SIZE, unit_size=UNIT_SIZE, force_stack=False,
                     align='left', unit_fill=GREY):
        """Gold-gradient 花字 price. The unit sits beside it, or on the next line."""
        plan = self.plan_price(x, force_stack=force_stack, align=align, price_size=size, unit_size=unit_size)
        return self.paint_price_plan(image, plan, base, unit_fill=unit_fill)

    def paint_photos(self, image, shot, y, width=None, x=None):
        """Paste the band or collage at y; returns its height.

        Width defaults to the full frame. A narrower width still shows the whole
        photo (side bars stay black); it is only used when the safe frame is short.
        """
        width = W if not width else int(width)
        x = (W - width) // 2 if x is None else int(x)
        if shot['kind'] != 'collage':
            band = self.resize_w(shot['photo'][1], width)
            image.paste(band, (x, y))
            return band.height
        scale = width / float(W)
        photos = shot['photos']
        extras = photos[1:3]
        lead_h = int(round(COLLAGE_LEAD_H * scale)) if extras else self.resize_w(photos[0][1], width).height
        image.paste(self.cover(photos[0][1], width, lead_h), (x, y))
        bottom = y + lead_h
        gap = max(1, int(round(GAP * scale)))
        pair_h = max(2, int(round(COLLAGE_PAIR_H * scale)))
        if len(extras) == 1:
            bottom += gap
            image.paste(self.cover(extras[0][1], width, pair_h), (x, bottom))
            bottom += pair_h
        elif len(extras) >= 2:
            bottom += gap
            left_w = (width - gap) // 2
            right_w = width - gap - left_w
            image.paste(self.cover(extras[0][1], left_w, pair_h), (x, bottom))
            image.paste(self.cover(extras[1][1], right_w, pair_h), (x + left_w + gap, bottom))
            bottom += pair_h
        return bottom - y

    def photo_height(self, shot):
        if shot['kind'] != 'collage':
            return self.resize_w(shot['photo'][1], W).height
        photos = shot['photos']
        if len(photos) == 1:
            return self.resize_w(photos[0][1], W).height
        return COLLAGE_LEAD_H + GAP + COLLAGE_PAIR_H

    def plate_band(self, shot):
        """Static composite of the photo plate (used for previews)."""
        return self.compose(shot, None)

    def _title_block(self, title, prefer_x=MX, max_right=None):
        max_right = W - SAFE if max_right is None else max_right
        return self.fit_lines(title, 'serif', L, MIN_TITLE, max_right, prefer_x=prefer_x,
                              stroke=4, shadow=(0, 8), blur=10)

    def _spec_lines(self, parts, size, prefer_x, max_right):
        parts = [p for p in parts if p]
        if not parts:
            return size, []
        size = int(size)
        while size >= MIN_TEXT:
            lines, cur = [], []
            for part in parts:
                trial = cur + [part]
                text = '   ·   '.join(trial)
                rel = self.rel_box(text, 'sans', size, 0, (0, 0), 0)
                x = max(prefer_x, SAFE - rel[0])
                if cur and x + rel[2] > max_right:
                    lines.append('   ·   '.join(cur))
                    cur = [part]
                else:
                    cur = trial
            if cur:
                lines.append('   ·   '.join(cur))
            ok = True
            for line in lines:
                rel = self.rel_box(line, 'sans', size, 0, (0, 0), 0)
                x = max(prefer_x, SAFE - rel[0])
                if x + rel[2] > max_right:
                    ok = False
                    break
            if ok:
                return size, lines
            if size == MIN_TEXT:
                return size, lines
            size -= 2
        return MIN_TEXT, ['   ·   '.join(parts)]

    def _block_rows(self, parts, size=S):
        """Centred colour-block captions: [[(text, width, size), ...], ...]."""
        parts = [p for p in parts if p]
        pad_x = 28
        max_w = W - 2 * SAFE
        rows, row, row_w = [], [], 0
        for part in parts:
            s = int(size)
            width = self.text_width(part, 'sans', s) + pad_x * 2
            while s > MIN_TEXT and width > max_w:
                s -= 2
                width = self.text_width(part, 'sans', s) + pad_x * 2
            if row and row_w + SP_S + width > max_w:
                rows.append(row)
                row, row_w = [], 0
            row.append((part, int(width), s))
            row_w += width if row_w == 0 else width + SP_S
        if row:
            rows.append(row)
        return rows

    def _strip_metrics(self, parts, x, right):
        parts = [p for p in parts if p]
        pad_x, pad_y = 28, 18
        if not parts:
            return {'lines': [], 'h': 0, 'size': MIN_TEXT, 'x': x, 'right': right,
                    'pad_x': pad_x, 'pad_y': pad_y, 'line_h': 0}
        max_w = max(40, (right - x) - pad_x * 2)
        join = '  ·  '

        def width(text, size):
            return self.text_width(text, 'sans', size)

        def pack(size):
            """Greedy lines of whole facts. Never splits a fact unless it is alone and still too wide."""
            lines, cur = [], []
            for part in parts:
                trial = cur + [part]
                text = join.join(trial)
                if cur and width(text, size) > max_w:
                    lines.append(join.join(cur))
                    cur = [part]
                else:
                    cur = trial
            if cur:
                lines.append(join.join(cur))
            fixed = []
            ok = True
            for line in lines:
                if width(line, size) <= max_w:
                    fixed.append(line)
                    continue
                ok = False
                _s, wrapped = self.fit_lines(line, 'sans', size, MIN_TEXT, x + pad_x + max_w,
                                             prefer_x=x + pad_x)
                fixed.extend([ln for ln, _x, _rel in wrapped] or [line])
            return fixed, ok

        size = M
        lines = [join.join(parts)]
        while size > MIN_TEXT and width(lines[0], size) > max_w:
            size -= 2
        if width(lines[0], size) > max_w:
            size = M
            while True:
                lines, ok = pack(size)
                if ok or size <= MIN_TEXT:
                    break
                size -= 2
        t, b = self.ink('国8', 'sans', size)
        line_h = b - t
        text_h = line_h * len(lines) + 8 * (len(lines) - 1)
        return {'lines': lines, 'h': text_h + pad_y * 2, 'size': size, 'x': x, 'right': right,
                'pad_x': pad_x, 'pad_y': pad_y, 'line_h': line_h}

    def _sync_photo(self, shot, origin, above, photo_h, photo_w, photo_x, below):
        """Match the pasted photo height after a width change."""
        if photo_w != W and shot.get('kind') != 'collage' and shot.get('photo'):
            photo_h = self.resize_w(shot['photo'][1], photo_w).height
            ceil = H - SAFE
            if origin + above + photo_h + below > ceil:
                origin = max(SAFE, ceil - (above + photo_h + below))
        return origin, photo_h, photo_w, photo_x

    def band_layout(self, shot):
        return {
            'gold_classic': self._layout_classic,
            'editorial': self._layout_editorial,
            'poster': self._layout_poster,
            'ledger': self._layout_ledger,
        }[self.template_name](shot)

    def _layout_classic(self, shot):
        """Tag, title, optional price, photo, pills. Title overlaps the photo on
        single-line room cards; a wrapped title or a wrapped unit price stays on black.
        """
        hero = bool(shot.get('hero'))
        title = shot.get('title') or ''
        size, title_lines = self._title_block(title, MX, W - SAFE)
        tag_present = bool(shot.get('tag'))
        tag_h = self.pill_height() if tag_present else 0
        head = (tag_h + TAG_GAP) if tag_present else 0
        if len(title_lines) == 1:
            t_top, t_bot = self.ink(title_lines[0][0], 'serif', size)
            title_bases = [head - t_top]
            title_bottom = title_bases[0] + t_bot
        else:
            title_bases, title_bottom = self._line_bases(title_lines, head, gap=12)
            t_bot = None
        price_plan = None
        price_base = None
        if hero and self.price:
            price_plan = self.plan_price(MX, W - SAFE)
            if len(title_lines) == 1:
                p_top, p_bot = self.ink(price_plan['price'], 'serif', price_plan['price_size'])
                price_base = title_bases[0] + t_bot + SP_M - p_top
            else:
                price_base = title_bottom + SP_M - price_plan['above']
            if price_plan['mode'] == 'stack':
                photo_rel = price_base + price_plan['below'] + SP_M
            elif len(title_lines) == 1:
                _pt, p_bot = self.ink(price_plan['price'], 'serif', price_plan['price_size'])
                photo_rel = price_base + p_bot + SP_M
            else:
                photo_rel = price_base + price_plan['below'] + SP_M
        else:
            overlap = shot.get('overlap', TITLE_OVERLAP)
            if len(title_lines) == 1 and overlap:
                photo_rel = title_bases[0] + t_bot - overlap
            else:
                photo_rel = title_bottom + SP_M
        photo_h = self.photo_height(shot)
        meta = shot.get('meta') or []
        chips_h = self.chips_height(meta)
        below = photo_h + (CHIP_GAP + chips_h if chips_h else 0)
        # photo_rel is the top of the photo inside the block, so "above" is photo_rel
        # and the photo height is counted inside `below` here. Split them for _contain.
        above = photo_rel
        tail = (CHIP_GAP + chips_h) if chips_h else 0
        origin, photo_h, photo_w, photo_x = self._contain(above, photo_h, tail, prefer_min=SAFE_TOP)
        origin, photo_h, photo_w, photo_x = self._sync_photo(shot, origin, above, photo_h, photo_w, photo_x, tail)
        return dict(
            hero=hero, title=title, size=size, origin=origin,
            title_lines=title_lines,
            title_bases=[origin + b for b in title_bases],
            title_base=origin + title_bases[0],
            price_plan=price_plan,
            price_base=None if price_base is None else origin + price_base,
            photo_y=origin + above, photo_h=photo_h, photo_x=photo_x, photo_w=photo_w,
            meta=meta, chips_h=chips_h,
        )

    def _layout_editorial(self, shot):
        """Photo on top. Kicker, title, rule, price and a spec line sit on black below."""
        hero = bool(shot.get('hero'))
        title = shot.get('title') or ''
        meta = [p for p in (shot.get('meta') or []) if p]
        kicker = shot.get('tag') or ''
        size, title_lines = self._title_block(title, MX, W - SAFE)
        price_plan = self.plan_price(MX, W - SAFE) if hero and self.price else None
        spec_size, spec_lines = self._spec_lines(meta, S, MX, W - SAFE)
        y = SP_L
        kicker_base = None
        if kicker:
            t, _b = self.ink(kicker, 'sans', S)
            kicker_base = y - t
            y = kicker_base + _b + SP_S
        title_bases, title_bottom = self._line_bases(title_lines, y, gap=12)
        y = title_bottom
        price_base = None
        if price_plan:
            y += SP_M
            price_base = y - price_plan['above']
            y = price_base + price_plan['below']
        y += SP_M
        rule_y = y
        y += 2 + SP_S
        spec_boxes = [(ln, MX, self.rel_box(ln, 'sans', spec_size, 0, (0, 0), 0)) for ln in spec_lines]
        spec_bases, spec_bottom = self._line_bases(spec_boxes, y, gap=8) if spec_boxes else ([], y)
        y = spec_bottom
        photo_h = self.photo_height(shot)
        origin, photo_h, photo_w, photo_x = self._contain(0, photo_h, y, prefer_min=SAFE)
        origin, photo_h, photo_w, photo_x = self._sync_photo(shot, origin, 0, photo_h, photo_w, photo_x, y)
        shift = origin + photo_h
        return dict(
            hero=hero, title=title, size=size,
            photo_y=origin, photo_h=photo_h, photo_x=photo_x, photo_w=photo_w,
            kicker=kicker, kicker_base=None if kicker_base is None else shift + kicker_base,
            title_lines=title_lines, title_bases=[shift + b for b in title_bases],
            price_plan=price_plan, price_base=None if price_base is None else shift + price_base,
            rule=(MX, shift + rule_y, min(W - SAFE, MX + 240), shift + rule_y + 2),
            spec_lines=spec_lines, spec_size=spec_size,
            spec_bases=[shift + b for b in spec_bases], meta=meta,
        )

    def _layout_poster(self, shot):
        """Centred type split by the photo: title above, colour blocks below."""
        hero = bool(shot.get('hero'))
        title = shot.get('title') or ''
        meta = [p for p in (shot.get('meta') or []) if p]
        tag = shot.get('tag') or ''
        size, title_lines = self._title_block(title, SAFE, W - SAFE)
        title_lines = [(text, self._center_x(rel), rel) for text, _x, rel in title_lines]
        price_plan = self.plan_price(SAFE, W - SAFE, force_stack=True, align='center') if hero and self.price else None
        blocks = self._block_rows(meta, S)
        y = 0
        tag_top = 0
        if tag:
            y += self.pill_height(S) + SP_M
        title_bases, title_bottom = self._line_bases(title_lines, y, gap=12)
        y = title_bottom
        price_base = None
        if price_plan:
            y += SP_S
            price_base = y - price_plan['above']
            y = price_base + price_plan['below']
        y += SP_M
        above = y
        block_h = self.pill_height(S)
        rows_n = len(blocks)
        tail = (SP_L + rows_n * block_h + max(0, rows_n - 1) * SP_S) if rows_n else 0
        photo_h = self.photo_height(shot)
        origin, photo_h, photo_w, photo_x = self._contain(above, photo_h, tail, prefer_min=SAFE)
        origin, photo_h, photo_w, photo_x = self._sync_photo(shot, origin, above, photo_h, photo_w, photo_x, tail)
        return dict(
            hero=hero, title=title, size=size, tag=tag, tag_top=origin + tag_top,
            title_lines=title_lines, title_bases=[origin + b for b in title_bases],
            price_plan=price_plan, price_base=None if price_base is None else origin + price_base,
            photo_y=origin + above, photo_h=photo_h, photo_x=photo_x, photo_w=photo_w,
            blocks=blocks, blocks_top=origin + above + photo_h + (SP_L if rows_n else 0),
            meta=meta,
        )

    def _layout_ledger(self, shot):
        """Left rail. Cover leads with the price. Captions are one gold strip."""
        hero = bool(shot.get('hero'))
        title = shot.get('title') or ''
        meta = [p for p in (shot.get('meta') or []) if p]
        text_x = SAFE + 36
        max_right = W - SAFE
        tag = shot.get('tag') or ''
        price_plan = None
        price_base = None
        kicker = ''
        kicker_base = None
        tag_top = None
        if hero and self.price:
            price_plan = self.plan_price(text_x, max_right, force_stack=True, align='left')
            size, title_lines = self._title_block(title, text_x, max_right)
            y = 0
            price_base = y - price_plan['above']
            y = price_base + price_plan['below'] + SP_M
            title_bases, title_bottom = self._line_bases(title_lines, y, gap=12)
            y = title_bottom
            if tag:
                y += SP_S
                t, b = self.ink(tag, 'sans', S)
                kicker_base = y - t
                kicker = tag
                y = kicker_base + b
            above = y + SP_M
        else:
            full_size, full_lines = self._title_block(title, text_x, max_right)
            size, title_lines = full_size, full_lines
            tag_h = self.pill_height(S) if tag else 0
            tag_w = (self.text_width(tag, 'sans', S, tracking=2) + 56) if tag else 0
            title_w = (title_lines[0][2][2] - title_lines[0][2][0]) if title_lines else 0
            inline = bool(tag) and len(title_lines) == 1 and (tag_w + SP_M + title_w) <= (max_right - text_x)
            if inline:
                title_x = text_x + tag_w + SP_S
                size, title_lines = self._title_block(title, title_x, max_right)
                if len(title_lines) == 1:
                    rel = title_lines[0][2]
                    row_h = max(tag_h, rel[3] - rel[1])
                    tag_top = (row_h - tag_h) // 2
                    title_bases = [(row_h - (rel[3] - rel[1])) // 2 - rel[1]]
                    above = row_h + SP_M
                else:
                    # The narrower measure wrapped. Keep the full-width lines.
                    inline = False
                    size, title_lines = full_size, full_lines
            if not inline:
                tag_top = 0 if tag else None
                y = (tag_h + SP_S) if tag else 0
                title_bases, title_bottom = self._line_bases(title_lines, y, gap=12)
                above = title_bottom + SP_M
        strip = self._strip_metrics(meta, text_x, max_right)
        tail = (SP_M + strip['h']) if strip['h'] else 0
        photo_h = self.photo_height(shot)
        origin, photo_h, photo_w, photo_x = self._contain(above, photo_h, tail, prefer_min=SAFE)
        origin, photo_h, photo_w, photo_x = self._sync_photo(shot, origin, above, photo_h, photo_w, photo_x, tail)
        photo_y = origin + above
        rail_bottom = photo_y - SP_S
        return dict(
            hero=hero, title=title, size=size, text_x=text_x,
            title_lines=title_lines, title_bases=[origin + b for b in title_bases],
            price_plan=price_plan, price_base=None if price_base is None else origin + price_base,
            kicker=kicker, kicker_base=None if kicker_base is None else origin + kicker_base,
            tag=tag if not hero else '', tag_top=None if tag_top is None else origin + tag_top,
            photo_y=photo_y, photo_h=photo_h, photo_x=photo_x, photo_w=photo_w,
            strip=strip, strip_top=photo_y + photo_h + (SP_M if strip['h'] else 0),
            rail=(SAFE, origin, SAFE + 8, max(origin + 8, rail_bottom)),
            meta=meta,
        )

    def paint_text(self, image, shot, lay):
        {
            'gold_classic': self._paint_classic,
            'editorial': self._paint_editorial,
            'poster': self._paint_poster,
            'ledger': self._paint_ledger,
        }[self.template_name](image, shot, lay)

    def _paint_titles(self, image, lay):
        for (text, x, _rel), base in zip(lay['title_lines'], lay['title_bases']):
            self.fancy(image, (x, base), text, 'serif', lay['size'], WHITE_STOPS,
                       stroke=4, shadow=(0, 8), blur=10, role='title')

    def _paint_kicker(self, draw, x, baseline, text, size=S):
        if not text or baseline is None:
            return
        tracking = 4
        size = int(size)
        while size > MIN_TEXT and x + self.text_width(text, 'sans', size, tracking) > W - SAFE:
            size -= 2
        self.draw(draw, (x, baseline), text, 'sans', size, GOLD, tracking=tracking, role='kicker')

    def _paint_blocks(self, draw, top, rows):
        if not rows:
            return top
        y = top
        for row in rows:
            height = self.pill_height(row[0][2])
            row_w = sum(w for _t, w, _s in row) + SP_S * (len(row) - 1)
            x = max(SAFE, (W - row_w) // 2)
            for text, width, size in row:
                rect = (int(x), int(y), int(x + width), int(y + height))
                if rect[2] > W - SAFE:
                    rect = (rect[0], rect[1], W - SAFE, rect[3])
                draw.rounded_rectangle(rect, radius=8, fill=GOLD)
                self._note(rect, text, 'caption', size)
                t, _b = self.ink('国8', 'sans', size)
                self.draw(draw, (rect[0] + 28, y + PILL_PAD_Y - t), text, 'sans', size,
                          '#0A0704', record=False)
                x += width + SP_S
            y += height + SP_S
        return y

    def _paint_strip(self, draw, top, strip):
        if not strip or not strip.get('lines'):
            return
        rect = (int(strip['x']), int(top), int(strip['right']), int(top + strip['h']))
        draw.rectangle(rect, fill=GOLD)
        t, _b = self.ink('国8', 'sans', strip['size'])
        yb = top + strip['pad_y'] - t
        inner_left = strip['x'] + strip['pad_x']
        inner_right = strip['right'] - strip['pad_x']
        for line in strip['lines']:
            tw = self.text_width(line, 'sans', strip['size'])
            x = inner_left + max(0, (inner_right - inner_left - tw) // 2)
            self.draw(draw, (int(x), int(yb)), line, 'sans', strip['size'], '#0A0704', role='caption')
            yb += strip['line_h'] + 8

    def _paint_classic(self, image, shot, lay):
        draw = ImageDraw.Draw(image)
        if shot.get('tag'):
            self.tag(draw, MX, lay['origin'], shot['tag'])
        self._paint_titles(image, lay)
        if lay.get('price_plan') and lay.get('price_base') is not None:
            self.paint_price_plan(image, lay['price_plan'], lay['price_base'], unit_fill=GREY)
        if lay.get('chips_h'):
            self.chips(draw, lay['photo_y'] + lay['photo_h'] + CHIP_GAP, lay['meta'],
                       first_filled=lay['hero'])

    def _paint_editorial(self, image, shot, lay):
        draw = ImageDraw.Draw(image)
        self._paint_kicker(draw, MX, lay.get('kicker_base'), lay.get('kicker') or '')
        self._paint_titles(image, lay)
        if lay.get('price_plan') and lay.get('price_base') is not None:
            self.paint_price_plan(image, lay['price_plan'], lay['price_base'], unit_fill=GOLD)
        rule = lay.get('rule')
        if rule:
            draw.rectangle(rule, fill=GOLD)
        for text, base in zip(lay.get('spec_lines') or [], lay.get('spec_bases') or []):
            self.draw(draw, (MX, base), text, 'sans', lay['spec_size'], INK, role='caption')

    def _paint_poster(self, image, shot, lay):
        draw = ImageDraw.Draw(image)
        if lay.get('tag'):
            self._paint_tag_centered(draw, lay['tag_top'], lay['tag'])
        self._paint_titles(image, lay)
        if lay.get('price_plan') and lay.get('price_base') is not None:
            self.paint_price_plan(image, lay['price_plan'], lay['price_base'], unit_fill=GOLD)
        self._paint_blocks(draw, lay.get('blocks_top', 0), lay.get('blocks') or [])

    def _paint_tag_centered(self, draw, top, text, size=S):
        pad_x = 28
        size = int(size)
        width = self.text_width(text, 'sans', size, tracking=2) + pad_x * 2
        while size > MIN_TEXT and width > W - 2 * SAFE:
            size -= 2
            width = self.text_width(text, 'sans', size, tracking=2) + pad_x * 2
        height = self.pill_height(size)
        x = max(SAFE, (W - width) // 2)
        rect = (int(x), int(top), int(min(W - SAFE, x + width)), int(top + height))
        draw.rounded_rectangle(rect, radius=12, fill=GOLD)
        self._note(rect, text, 'tag', size)
        t, _b = self.ink('国8', 'sans', size)
        self.draw(draw, (rect[0] + pad_x, top + PILL_PAD_Y - t), text, 'sans', size,
                  '#0A0704', tracking=2, record=False)

    def _paint_ledger(self, image, shot, lay):
        draw = ImageDraw.Draw(image)
        rail = lay.get('rail')
        if rail and rail[3] > rail[1]:
            draw.rectangle(rail, fill=GOLD)
        if lay.get('tag') and lay.get('tag_top') is not None:
            self.tag(draw, lay['text_x'], lay['tag_top'], lay['tag'])
        if lay.get('price_plan') and lay.get('price_base') is not None:
            self.paint_price_plan(image, lay['price_plan'], lay['price_base'], unit_fill=GOLD)
        self._paint_titles(image, lay)
        self._paint_kicker(draw, lay['text_x'], lay.get('kicker_base'), lay.get('kicker') or '')
        self._paint_strip(draw, lay.get('strip_top', 0), lay.get('strip'))

    # ---- layers: static base + matted text overlay + animated photo regions --
    def layers(self, shot):
        """Per-shot render layers, cached.

        base    RGB black canvas with every photo at its static framing
        tb, inv premultiplied text colour and (255 - alpha), recovered by drawing the
                exact same text once on black and once on white (difference matte),
                so the overlay is pixel-identical to the approved static plates
        kb      animated regions: the band photo, or a collage's lead tile
        """
        key = ('layers', shot.get('plate'), tuple(shot.get('files') or ()))
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        if shot['kind'] == 'end':
            base = self.plate_end()
            hit = dict(base=base, base_np=np.asarray(base), tb=None, inv=None, kb=[])
            self.cache[key] = hit
            return hit
        lay = self.band_layout(shot)
        base = Image.new('RGB', (W, H), BLACK)
        px, pw = lay.get('photo_x', 0), lay.get('photo_w', W)
        self.paint_photos(base, shot, lay['photo_y'], pw, px)
        on_black = Image.new('RGB', (W, H), '#000000')
        on_white = Image.new('RGB', (W, H), '#FFFFFF')
        self.paint_text(on_black, shot, lay)
        self.paint_text(on_white, shot, lay)
        tb = np.asarray(on_black).astype(np.int16)
        tw = np.asarray(on_white).astype(np.int16)
        inv = np.clip((tw - tb).mean(axis=2, keepdims=True), 0, 255)   # 255 - alpha
        kb = []
        move = shot.get('kb')
        if move:
            if shot['kind'] == 'collage':
                photo = shot['photos'][0]
                height = COLLAGE_LEAD_H if len(shot['photos']) > 1 else lay['photo_h']
                if pw != W:
                    height = max(2, int(round(height * pw / W)))
            else:
                photo, height = shot['photo'], lay['photo_h']
            kb.append(dict(src=photo[1], rect=(px, lay['photo_y'], pw, height),
                           move=move, strength=shot.get('kb_strength', 0.0)))
        hit = dict(base=base, base_np=np.asarray(base), tb=tb.astype(np.uint16),
                   inv=inv.astype(np.uint16), kb=kb)
        self.cache[key] = hit
        return hit

    def kb_source(self, photo, w, h, strength):
        """Pre-scale the source so per-frame resampling stays close to 1:1 (only
        ever downscales by <= ~15%, never aliasing); small sources are kept."""
        key = ('kbsrc', id(photo), w, h)
        hit = self.cache.get(key)
        if hit is None:
            sw, sh = photo.size
            bw = min(sw, sh * w / h)
            f = min(1.0, w * (1 + strength) * 1.15 / bw)
            hit = photo if f >= 0.999 else photo.resize((round(sw * f), round(sh * f)),
                                                        Image.Resampling.LANCZOS)
            self.cache[key] = hit
        return hit

    def kb_window(self, region, p, pulse=1.0):
        """Float crop window (x0, y0, cw, ch) in source pixels at progress p."""
        src = self.kb_source(region['src'], region['rect'][2], region['rect'][3], region['strength'])
        sw, sh = src.size
        _, _, w, h = region['rect']
        bw, bh = (sh * w / h, sh) if sw / sh > w / h else (sw, sw * h / w)
        z0, z1, cx0, cx1, cy0, cy1 = KB_MOVES[region['move']]
        s = region['strength']
        z0, z1 = 1 + (z0 - 1) * s / 0.08, 1 + (z1 - 1) * s / 0.08
        e = 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, p)))      # ease-in-out
        z = (z0 + (z1 - z0) * e) * max(1.0, pulse)
        cw, ch = bw / z, bh / z
        # Pan within the slack the *current* zoom leaves, so the window never
        # leaves the photo (no black edges), whatever the move.
        amp_x, amp_y = (bw - cw) / 2, (bh - ch) / 2
        cx = sw / 2 + (cx0 + (cx1 - cx0) * e) * amp_x
        cy = sh / 2 + (cy0 + (cy1 - cy0) * e) * amp_y
        return src, (cx - cw / 2, cy - ch / 2, cw, ch)

    def kb_render(self, region, p, pulse=1.0):
        src, (x0, y0, cw, ch) = self.kb_window(region, p, pulse)
        _, _, w, h = region['rect']
        # Sub-pixel affine sampling (BICUBIC): no integer stair-stepping.
        return src.transform((w, h), Image.Transform.AFFINE,
                             (cw / w, 0, x0, 0, ch / h, y0), resample=Image.Resampling.BICUBIC)

    def compose(self, shot, p, pulse=1.0):
        """Frame for one shot at Ken Burns progress p (None = static framing).

        `pulse` is a short extra zoom on the photo only (text stays put), used
        for the 1–2 frame beat hit inside long shots.
        """
        lay = self.layers(shot)
        if lay['tb'] is None:
            return lay['base']
        if p is None or not lay['kb'] or not self.kenburns:
            base = lay['base_np']
        else:
            canvas = lay['base'].copy()
            for region in lay['kb']:
                canvas.paste(self.kb_render(region, p, pulse), region['rect'][:2])
            base = np.asarray(canvas)
        out = (base.astype(np.uint16) * lay['inv'] + 127) // 255 + lay['tb']
        return Image.fromarray(np.minimum(out, 255).astype(np.uint8), 'RGB')

    def shot_frame(self, index, local, pulse=1.0):
        shot = self.shots[index]
        pre, post = shot.get('_pre', 0.0), shot.get('_post', 0.0)
        span = shot['dur'] + pre + post
        return self.compose(shot, (local + pre) / span if span > 0 else 0.0, pulse)

    def _pulse_zoom(self, time, shot):
        """1–2 frame photo zoom on a strong beat inside a long shot. Never at t=0."""
        if not self.beat_pulse or shot.get('kind') == 'end' or shot.get('dur', 0) < 2.0:
            return 1.0
        if time < 0.05 or not self.strong_beats:
            return 1.0
        dt = min(abs(time - b) for b in self.strong_beats)
        frame = 1.0 / max(1, self.fps)
        if dt <= 0.5 * frame:
            amp = 1.0
        elif dt <= 1.0 * frame:
            amp = 0.40
        else:
            return 1.0
        return 1.0 + 0.018 * amp

    # ---- motion + transitions assignment -----------------------------------
    def beat_sync(self, beats, window=0.40, min_shot=1.2, downbeats=None, strength=None,
                  phrase_onsets=None):
        """Snap cuts onto phrase onsets and bar lines. Individual kicks are ignored.

        `beats` and `strength` are accepted for call compatibility and are not
        used as snap targets. Each shot stays inside its dur_lo/dur_hi band.
        Total duration stays inside 15–20s when those bands allow it.
        """
        del beats, strength, min_shot
        return self.phrase_align(downbeats or [], phrase_onsets or self.phrase_onsets,
                                 window=window)

    def align_to_phrase(self, downbeats, phrase_onsets, window=0.40, offset_limit=0.40):
        """Try playback offsets inside ±offset_limit and keep the best grid fit.

        The detected phrase onset stays within ±offset_limit of frame 0. A small
        offset lets more cuts land on a bar or a two-bar phrase without leaving
        the per-shot duration bands. Returns the chosen offset (seconds added
        to the phrase onset to get the audio start).
        """
        base = [(float(s.get('dur_plan', s['dur'])), float(s.get('dur_lo', s['dur'])),
                 float(s.get('dur_hi', s['dur']))) for s in self.shots]
        bars0 = [float(b) for b in downbeats]
        phrases0 = [float(p) for p in phrase_onsets]
        steps = [round(i * 0.02, 4) for i in range(-int(round(offset_limit / 0.02)),
                                                    int(round(offset_limit / 0.02)) + 1)]
        best = None
        for delta in steps:
            for shot, (plan, lo, hi) in zip(self.shots, base):
                shot['dur'] = plan
                shot['dur_plan'] = plan
                shot['dur_lo'] = lo
                shot['dur_hi'] = hi
            self.phrase_align([b - delta for b in bars0], [p - delta for p in phrases0],
                              window=window, reflow=False)
            hits = sum(1 for sn in self.phrase_snaps if sn['hit'] in ('phrase', 'bar'))
            score = (hits, -abs(self.duration - 17.5), -abs(delta))
            if best is None or score > best[0]:
                best = (score, delta)
        delta = 0.0 if best is None else best[1]
        for shot, (plan, lo, hi) in zip(self.shots, base):
            shot['dur'] = plan
            shot['dur_plan'] = plan
            shot['dur_lo'] = lo
            shot['dur_hi'] = hi
        self.downbeats = [round(b - delta, 4) for b in bars0]
        self.phrase_onsets = [round(p - delta, 4) for p in phrases0]
        self.phrase_offset = delta
        self.phrase_align(self.downbeats, self.phrase_onsets, window=window, reflow=True)
        return delta

    def phrase_align(self, downbeats, phrase_onsets, window=0.40, target_total=17.5, reflow=True):
        """Place each cut on a melodic phrase onset or a bar line, within ±window.

        A move is kept only when every shot duration stays inside its band, so a
        bar that would stretch 小区 past 2.0s is not taken. Kicks are not targets.
        Returns the new cut times.
        """
        shots = self.shots
        n = len(shots)
        if n < 2:
            self.phrase_snaps = []
            self.beat_deltas = []
            return []
        step = 0.02
        window = float(window)

        def q(value):
            return int(round(float(value) / step))

        phrases = sorted(float(p) for p in (phrase_onsets or []) if float(p) > 0.05)
        bars = sorted(set(round(float(b), 4) for b in (downbeats or []) if float(b) > 0.05))
        # Phrase onsets are bar-aligned musically; keep them in the bar list too.
        for phrase in phrases:
            if not any(abs(phrase - bar) <= 0.03 for bar in bars):
                bars.append(phrase)
        bars.sort()

        def cut_score(t):
            def nearest(cands):
                if not cands:
                    return None
                hit = min(cands, key=lambda item: abs(item - t))
                dist = abs(hit - t)
                return (hit, dist) if dist <= window + 1e-9 else None
            phrase_hit = nearest(phrases)
            if phrase_hit is not None:
                return 3.4 - 8.0 * phrase_hit[1]
            bar_hit = nearest(bars)
            if bar_hit is not None:
                return 1.8 - 5.0 * bar_hit[1]
            if bars:
                return -0.20 - 0.05 * min(abs(bar - t) for bar in bars)
            return 0.0

        hi_sum = sum(float(s.get('dur_hi', s['dur'])) for s in shots)
        tmax = min(20.0, hi_sum)
        nbin = q(tmax) + 3
        neg = -1e12
        current = np.full(nbin, neg)
        current[0] = 0.0
        backs = []
        for k, shot in enumerate(shots):
            lo = float(shot.get('dur_lo', shot['dur']))
            hi = float(shot.get('dur_hi', shot['dur']))
            plan = float(shot.get('dur_plan', shot['dur']))
            nxt = np.full(nbin, neg)
            bp = np.full(nbin, -1, np.int32)
            live = np.where(current > neg / 2)[0]
            for ti in live:
                t = ti * step
                a = q(t + lo)
                b = min(nbin - 1, q(t + hi))
                base = float(current[ti])
                for tj in range(max(0, a), b + 1):
                    nt = tj * step
                    score = base - 0.35 * abs((nt - t) - plan)
                    if k < n - 1:
                        score += cut_score(nt)
                    elif 17.1 <= nt <= 18.0:
                        # Prefer ~17.5s over collecting one more musical hit at 16s.
                        score += 9.0 - abs(nt - target_total) * 0.4
                    elif 15.0 <= nt <= 20.0:
                        score += 0.6 - abs(nt - target_total) * 1.6
                    else:
                        score -= 12.0
                    if score > nxt[tj]:
                        nxt[tj] = score
                        bp[tj] = ti
            backs.append(bp)
            current = nxt
        legal = [i for i in range(nbin) if current[i] > neg / 2 and 15.0 - 1e-6 <= i * step <= 20.0 + 1e-6]
        if legal:
            best = max(legal, key=lambda i: current[i])
        else:
            best = int(np.argmax(current))
            if current[best] <= neg / 2:
                self.phrase_snaps = []
                self.beat_deltas = []
                return [sum(s['dur'] for s in shots[:k + 1]) for k in range(n - 1)]
        ends = [best]
        for k in range(n - 1, -1, -1):
            prev = int(backs[k][ends[-1]])
            if prev < 0:
                break
            ends.append(prev)
        ends = ends[::-1]
        if len(ends) != n + 1 or ends[0] != 0:
            self.phrase_snaps = []
            self.beat_deltas = []
            return [sum(s['dur'] for s in shots[:k + 1]) for k in range(n - 1)]
        planned = []
        acc = 0.0
        for shot in shots:
            acc += shot['dur']
            planned.append(acc)
        for shot, a, b in zip(shots, ends, ends[1:]):
            dur = round((b - a) * step, 4)
            lo = float(shot.get('dur_lo', dur))
            hi = float(shot.get('dur_hi', dur))
            dur = min(hi, max(lo, dur))
            shot['dur'] = round(dur, 4)
        # The last shot absorbs the rounding so the sum matches the grid end,
        # then is clamped back into its band (a 0.02 grid step fits the band).
        total = round(ends[-1] * step, 4)
        drift = round(total - sum(s['dur'] for s in shots), 4)
        if drift:
            last = shots[-1]
            last['dur'] = round(min(last['dur_hi'], max(last['dur_lo'], last['dur'] + drift)), 4)
        self.duration = round(sum(s['dur'] for s in shots), 4)
        new = []
        acc = 0.0
        snaps = []
        deltas = []
        for k, shot in enumerate(shots[:-1]):
            acc += shot['dur']
            new.append(round(acc, 4))
            delta = round(acc - planned[k], 4)
            deltas.append(delta)
            phrase_dist = min((abs(p - acc), p) for p in phrases) if phrases else (99.0, None)
            bar_dist = min((abs(b - acc), b) for b in bars) if bars else (99.0, None)
            # "On" the point (grid tolerance). A cut merely inside the ±window
            # that the shot band would not let us move is reported as near/hold.
            on = 0.06
            if phrase_dist[0] <= on:
                kind, target, dist = 'phrase', phrase_dist[1], phrase_dist[0]
            elif bar_dist[0] <= on:
                kind, target, dist = 'bar', bar_dist[1], bar_dist[0]
            elif min(phrase_dist[0], bar_dist[0]) <= window + 1e-6:
                nearer = phrase_dist if phrase_dist[0] <= bar_dist[0] else bar_dist
                kind, target, dist = 'near', nearer[1], nearer[0]
            else:
                kind, target, dist = 'hold', (bar_dist[1] if bars else None), bar_dist[0]
            snaps.append({
                'index': k,
                'planned': round(planned[k], 4),
                'time': round(acc, 4),
                'delta': delta,
                'hit': kind,
                'target': None if target is None else round(float(target), 4),
                'distance': None if dist >= 90 else round(float(dist), 4),
            })
        self.beat_deltas = deltas
        self.phrase_snaps = snaps
        acc, sections = 0.0, {}
        for shot in self.shots:
            sec = sections.setdefault(shot['index'], [acc, 0.0])
            sec[1] += shot['dur']
            acc += shot['dur']
        for sec, (start, dur) in zip(self.sections, sections.values()):
            sec['start'], sec['duration'] = round(start, 4), round(dur, 4)
        if reflow:
            self.cache = {k: v for k, v in self.cache.items()
                          if not (isinstance(k, tuple) and k and k[0] in ('kbsrc', 'layers'))}
            self.plates = {}
            self.assign_motion(self._transitions, self._transition_dur)
        return new

    def _plan_transitions(self, n):
        """Return (plan, varied_duration). plan is [(kind, direction), ...] or None for auto."""
        spec = str(self._transitions or 'random').strip().lower()
        rng = random.Random(self.seed)
        if spec in ('random', 'rand'):
            # Deal the pool without replacement so a short film shows the set,
            # then reshuffle. The seed is stable; the previous kind never repeats.
            bag = []
            plan = []
            prev = None
            while len(plan) < n:
                if not bag:
                    bag = list(self.transition_pool)
                    rng.shuffle(bag)
                    if prev is not None and bag[0] == prev and len(bag) > 1:
                        bag[0], bag[1] = bag[1], bag[0]
                kind = bag.pop(0)
                direction = None
                if kind == 'whip':
                    direction = rng.choice(('left', 'right', 'up'))
                elif kind == 'spin':
                    direction = rng.choice(('cw', 'ccw'))
                plan.append((kind, direction))
                prev = kind
            return plan, True
        if spec == 'auto':
            return None, False
        names = [canonical_transition(t) for t in spec.split(',') if t.strip()]
        bad = [t for t in names if t not in TRANSITIONS]
        if bad or not names:
            raise ValueError(f'Unknown transition(s): {bad or names}; choose from {sorted(TRANSITIONS)} '
                             'or random/auto')
        plan = []
        for i in range(n):
            kind = names[i % len(names)]
            direction = None
            if kind == 'whip':
                direction = ('left', 'right', 'up')[i % 3]
            elif kind == 'spin':
                direction = 'cw' if i % 2 == 0 else 'ccw'
            plan.append((kind, direction))
        return plan, False

    def assign_motion(self, transitions='random', transition_dur=0.5):
        self._transitions, self._transition_dur = transitions, float(transition_dur)
        band_cycle = ['push_in', 'pan_lr', 'pan_rl', 'diag_in', 'pull_out']
        collage_cycle = ['pull_out', 'push_in']
        bi = ci = 0
        for shot in self.shots:
            shot['kb'], shot['kb_strength'] = None, 0.0
            if not self.kenburns or shot['kind'] == 'end':
                continue
            if shot['kind'] == 'collage':
                shot['kb'] = collage_cycle[ci % len(collage_cycle)]
                ci += 1
                scale = 0.5             # lead tile only, very subtle
            elif shot.get('label') == '户型':
                shot['kb'], scale = 'push_in', 0.4   # drawing: gentle push only
            else:
                shot['kb'] = band_cycle[bi % len(band_cycle)]
                bi += 1
                scale = 1.0
            # Same perceived speed on short shots: amplitude follows screen time.
            visible = shot['dur'] + self._transition_dur
            shot['kb_strength'] = self.kb_strength * scale * min(1.0, visible / 4.0)

        plan, varied = self._plan_transitions(max(0, len(self.shots) - 1))
        rotation = ['slide_left', 'wipe', 'slide_up', 'fade', 'slide_right']
        ri = 0
        self.cuts = []
        for k in range(len(self.shots) - 1):
            a, b = self.shots[k], self.shots[k + 1]
            direction = None
            if plan is not None:
                kind, direction = plan[k]
            elif b['kind'] == 'end':
                kind = 'black'
            elif a.get('index') == b.get('index') and a.get('title') == b.get('title'):
                kind = 'zoom'           # same subject (single -> collage): push through
            else:
                kind = rotation[ri % len(rotation)]
                ri += 1
            override = getattr(self, 'cut_overrides', {}).get(k)
            if override:
                kind, direction = override, None
            if kind == 'cut':
                dur = 0.0
            else:
                # Random mode uses the per-effect length (0.34–0.40s). The CLI cap
                # can only shorten down to the floor — never to a hard cut.
                floor = TRANSITION_FLOOR.get(kind, 0.32)
                preferred = TRANSITION_SECONDS.get(kind, 0.36)
                dur = min(preferred, max(floor, float(self._transition_dur))) if varied else min(
                    max(float(self._transition_dur), floor), max(preferred, floor))
                if varied:
                    dur = min(preferred, dur)
                dur = max(floor, dur)
                dur = min(dur, 0.70 * min(a['dur'], b['dur']))
                if dur + 1e-6 < floor:
                    dur = min(floor, 0.70 * min(a['dur'], b['dur']))
                dur = max(0.28, dur)
            dissolve = kind in DISSOLVE_KINDS
            self.cuts.append(dict(type=kind, dur=round(dur, 4), dir=direction,
                                  sfx=sfx_tools.sfx_for(kind),
                                  dissolve=dissolve,
                                  mid_alpha=0.5 if dissolve else None))
            a['transition_out'] = kind if not direction else f'{kind}:{direction}'
            a['transition_dir'] = direction
        for k, shot in enumerate(self.shots):
            shot['_pre'] = self.cuts[k - 1]['dur'] / 2 if k > 0 else 0.0
            shot['_post'] = self.cuts[k]['dur'] / 2 if k < len(self.cuts) else 0.0
        self.starts = []
        acc = 0.0
        for shot in self.shots:
            self.starts.append(acc)
            acc += shot['dur']
        for k, cut in enumerate(self.cuts):
            cut['time'] = round(self.starts[k + 1], 4)

    def _seam(self, out, seam, axis):
        """Full-height (or full-width) gold streak so the moving edge reads on black."""
        gold = np.array([255.0, 236.0, 200.0], np.float32)
        half = 26
        if axis == 'x':
            if seam <= 0 or seam >= W:
                return out
            x0, x1 = max(0, seam - half), min(W, seam + half)
            span = x1 - x0
            if span <= 0:
                return out
            ridge = np.clip(np.sin(np.linspace(0, math.pi, span, dtype=np.float32)), 0, None) ** 0.5
            out[:, x0:x1] = out[:, x0:x1] * (1 - 0.92 * ridge[None, :, None]) + gold * (0.92 * ridge[None, :, None])
        else:
            if seam <= 0 or seam >= H:
                return out
            y0, y1 = max(0, seam - half), min(H, seam + half)
            span = y1 - y0
            if span <= 0:
                return out
            ridge = np.clip(np.sin(np.linspace(0, math.pi, span, dtype=np.float32)), 0, None) ** 0.5
            out[y0:y1] = out[y0:y1] * (1 - 0.92 * ridge[:, None, None]) + gold * (0.92 * ridge[:, None, None])
        return out

    def _tr_whip(self, a, b, p, direction):
        # Smoothstep keeps the slide readable across the whole window, not a 2-frame smear.
        e = p * p * (3 - 2 * p)
        blur = int(round(150 * (math.sin(math.pi * p) ** 0.5)))
        vertical = direction == 'up'
        sign = 1 if direction == 'right' else -1
        out = _whip_slide(a, b, e, vertical, sign, blur)
        if vertical:
            shift = int(round(e * H))
            seam = (H - shift) if sign < 0 else shift
            out = self._seam(out, seam, 'y')
        else:
            shift = int(round(e * W))
            seam = (W - shift) if sign < 0 else shift
            out = self._seam(out, seam, 'x')
        return _u8(out)

    def _tr_zoom_blur(self, a, b, p):
        e = p * p * (3 - 2 * p)
        amount = math.sin(math.pi * p) ** 0.65
        mixed = _zoom_blur(a, amount) * (1 - e) + _zoom_blur(b, amount) * e
        punch = math.sin(math.pi * p) ** 0.75
        mixed = mixed * (1 - 0.18 * punch) + 255.0 * (0.18 * punch)
        return _u8(mixed)

    def _tr_flash(self, a, b, p):
        # White holds across the middle of the window so the flash is several frames, not one.
        if p < 0.22:
            white = p / 0.22
            base = _f32(a)
        elif p > 0.78:
            white = (1.0 - p) / 0.22
            base = _f32(b)
        else:
            white = 1.0
            e = (p - 0.22) / 0.56
            base = _f32(a) * (1 - e) + _f32(b) * e
        return _u8(base * (1.0 - white) + 255.0 * white)

    def _tr_glitch(self, a, b, p):
        e = p * p * (3 - 2 * p)
        s = math.sin(math.pi * p) ** 0.45
        aa, bb = _f32(a), _f32(b)
        bands = 14
        bh = H // bands
        phase = (self.seed % 997) * 0.01
        mashed = np.empty_like(aa)
        for i in range(bands):
            y0 = i * bh
            y1 = H if i == bands - 1 else (i + 1) * bh
            # Odd slices pull in the incoming frame only once the effect is up.
            src = bb if (i % 2 == 1 and s > 0.25) else aa
            off = int(round(math.sin(i * 1.7 + phase + p * 8.0) * 150 * s))
            mashed[y0:y1] = np.roll(src[y0:y1], off, axis=1)
        out = mashed * (1 - e) + bb * e
        shift = int(round(90 * s))
        rgb = out.copy()
        rgb[..., 0] = np.roll(out[..., 0], shift, axis=1)
        rgb[..., 2] = np.roll(out[..., 2], -int(round(shift * 0.75)), axis=1)
        if s > 0.35:
            y = int((0.12 + 0.7 * p) * (H - 8))
            rgb[y:y + 4] = np.clip(rgb[y:y + 4] * 1.7 + 36, 0, 255)
        return _u8(rgb)

    def _tr_light(self, a, b, p):
        e = p * p * (3 - 2 * p)
        base = _f32(a) * (1 - e) + _f32(b) * e
        xs = np.linspace(0, 1, W, dtype=np.float32)
        ys = np.linspace(-1, 1, H, dtype=np.float32)
        cx = -0.25 + 1.5 * e
        band = np.exp(-((xs - cx) ** 2) / 0.018)
        wide = np.exp(-((xs - cx) ** 2) / 0.10)
        yy = ys[:, None]
        veil = (0.72 * np.exp(-(yy ** 2) / 0.70) * wide + np.exp(-(yy ** 2) / 0.22) * band)
        strength = 1.65 * math.sin(math.pi * max(p, 0.0))
        gold = np.array([255.0, 196.0, 110.0], np.float32)
        hot = np.array([255.0, 248.0, 230.0], np.float32)
        leak = veil[..., None] * strength
        core = (np.exp(-(yy ** 2) / 0.20) * band)[..., None]
        color = gold * leak + (hot - gold) * (core * strength)
        inv = (1.0 - base / 255.0) * (1.0 - np.clip(color / 255.0, 0, 1))
        return _u8((1.0 - inv) * 255.0)

    def _tr_shake(self, a, b, p):
        src = _f32(a if p < 0.5 else b)
        amp = math.sin(math.pi * p) ** 0.75
        # Displacement peaks on the impact frame, then rings out. Ends are still.
        dx = int(round(44 * amp * math.sin((p - 0.5) * math.pi * 6 + math.pi / 2)))
        dy = int(round(28 * amp * math.sin((p - 0.5) * math.pi * 8 + 0.6)))
        out = _shift_edge(src, dx, dy)
        hit = math.exp(-((p - 0.5) ** 2) / 0.004)
        return _u8(np.clip(out * (1 + 0.14 * hit), 0, 255))

    def _tr_spin(self, a, b, p, direction):
        e = p * p * (3 - 2 * p)
        sign = -1.0 if direction == 'cw' else 1.0
        spread = 11.0 * math.sin(math.pi * p)
        aa = _spin_frame(a, sign * 26.0 * e, spread)
        bb = _spin_frame(b, sign * 26.0 * (e - 1.0), spread)
        return _u8(aa * (1 - e) + bb * e)

    def _slide(self, a, b, p, axis, sign):
        e = p * p * (3 - 2 * p)
        vel = 6 * p * (1.0 - p)
        blur = int(round(52 * min(1.0, vel / 1.5)))
        aa, bb = _f32(a), _f32(b)
        if blur >= 2:
            aa = _box_blur(aa, blur, 0 if axis == 'y' else 1)
            bb = _box_blur(bb, blur, 0 if axis == 'y' else 1)
        out = np.empty_like(aa)
        if axis == 'x':
            shift = max(0, min(W, int(round(e * W))))
            if shift <= 0:
                out[:] = aa
                seam = W if sign < 0 else 0
            elif shift >= W:
                out[:] = bb
                seam = 0 if sign < 0 else W
            elif sign < 0:
                out[:, :W - shift] = aa[:, shift:]
                out[:, W - shift:] = bb[:, :shift]
                seam = W - shift
            else:
                out[:, shift:] = aa[:, :W - shift]
                out[:, :shift] = bb[:, W - shift:]
                seam = shift
            out = self._seam(out, seam, 'x')
        else:
            shift = max(0, min(H, int(round(e * H))))
            if shift <= 0:
                out[:] = aa
                seam = H
            elif shift >= H:
                out[:] = bb
                seam = 0
            else:
                out[:H - shift] = aa[shift:]
                out[H - shift:] = bb[:shift]
                seam = H - shift
            out = self._seam(out, seam, 'y')
        return _u8(out)

    def transition(self, kind, a, b, p, cut=None):
        kind = canonical_transition(kind)
        cut = cut or {}
        if kind == 'fade':
            return Image.blend(a, b, _ease(p, 2.0))
        if kind == 'black':
            e = _ease(p, 2.0)
            return Image.blend(a, self.black, e * 2) if e < 0.5 else Image.blend(self.black, b, e * 2 - 1)
        if kind in ('push', 'slide_left'):
            return self._slide(a, b, p, 'x', -1)
        if kind == 'slide_right':
            return self._slide(a, b, p, 'x', 1)
        if kind == 'slide_up':
            return self._slide(a, b, p, 'y', -1)
        if kind == 'wipe':
            e = p * p * (3 - 2 * p)
            edge = 380.0
            pos = -edge + e * (W + 2 * edge)
            row = np.clip((pos - np.arange(W, dtype=np.float32)) / edge + 0.5, 0, 1)
            mask = Image.fromarray((row * 255).astype(np.uint8)[None, :], 'L').resize(
                (W, H), Image.Resampling.NEAREST)
            mixed = np.asarray(Image.composite(b, a, mask), np.float32)
            dist = np.abs(np.arange(W, dtype=np.float32) - pos)
            ridge = np.clip(1.0 - dist / 34.0, 0, 1) * math.sin(math.pi * p)
            gold = np.array([255.0, 228.0, 170.0], np.float32)
            mixed = mixed * (1 - 0.95 * ridge[None, :, None]) + gold * (0.95 * ridge[None, :, None])
            return _u8(mixed)
        if kind == 'zoom':
            # zoom-dissolve: blend weight is smoothstep, so the midpoint is α = 0.5.
            e = p * p * (3 - 2 * p)

            def scaled(img, s):
                s = max(1.0, s)          # 1.14 - 0.14 == 0.99999… in float
                cw, ch = W / s, H / s
                box = ((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2)
                return img.resize((W, H), Image.Resampling.BILINEAR, box=box)
            return Image.blend(scaled(a, 1 + 0.14 * e), scaled(b, 1.14 - 0.14 * e), e)
        if kind == 'whip':
            return self._tr_whip(a, b, p, cut.get('dir') or 'left')
        if kind == 'zoom_blur':
            return self._tr_zoom_blur(a, b, p)
        if kind == 'flash':
            return self._tr_flash(a, b, p)
        if kind == 'glitch':
            return self._tr_glitch(a, b, p)
        if kind == 'light_leak':
            return self._tr_light(a, b, p)
        if kind == 'shake':
            return self._tr_shake(a, b, p)
        if kind == 'spin':
            return self._tr_spin(a, b, p, cut.get('dir') or 'cw')
        return b if p >= 0.5 else a     # 'cut'

    def plate_collage(self, shot):
        return self.plate_band(shot)

    def end_rows(self):
        floor = self.floor
        if self.total_floors:
            floor = f'{floor}/共{self.total_floors}' if floor else f'共{self.total_floors}'
        area = self.area
        if area and self.inner_area:
            area = f'{area}（套内{self.inner_area}）'
        rows = [('户型', self.layout_full), ('面积', area), ('朝向', self.orientation),
                ('楼层', floor), ('装修', self.decoration), ('建成', self.year),
                ('区域', self.place.replace(' · ', '·'))]
        return [(k, v) for k, v in rows if v]

    def _end_origin(self, total, prefer_min=SAFE_TOP):
        origin = max(prefer_min, (H - total) // 2)
        if origin + total > H - SAFE:
            origin = max(SAFE, H - SAFE - total)
        if origin >= SAFE and origin + total <= H - SAFE:
            snapped = snap(origin)
            if snapped >= SAFE and snapped + total <= H - SAFE:
                origin = snapped
        return int(max(SAFE, origin))

    def plate_end(self):
        return {
            'gold_classic': self._end_classic,
            'editorial': self._end_editorial,
            'poster': self._end_poster,
            'ledger': self._end_ledger,
        }[self.template_name]()

    def _paint_name_lines(self, image, name_lines, name_bases, name_size, origin):
        for (text, x, _rel), base in zip(name_lines, name_bases):
            self.fancy(image, (x, origin + base), text, 'serif', name_size, WHITE_STOPS,
                       stroke=4, shadow=(0, 8), blur=10, role='title')

    def _end_classic(self):
        """Left sheet: gold block, name, price, then one label/value row per fact."""
        image = Image.new('RGB', (W, H), BLACK)
        draw = ImageDraw.Draw(image)
        rows = self.end_rows()
        value_col = MX + 2 * S + SP_L
        name = self.community or '精选好房'
        name_size, name_lines = self._title_block(name, MX, W - SAFE)
        price_plan = self.plan_price(MX, W - SAFE)
        y = self.pill_height() + TAG_GAP
        name_bases, name_bottom = self._line_bases(name_lines, y, 12)
        price_base = name_bottom + SP_M - price_plan['above']
        y = price_base + price_plan['below'] + SP_L
        row_layouts = []
        for label, value in rows:
            vsize, vlines = self.fit_lines(value, 'sans', M, MIN_TEXT, W - SAFE, prefer_x=value_col)
            if not vlines:
                continue
            line_h = vlines[0][2][3] - vlines[0][2][1]
            block = line_h * len(vlines) + 8 * (max(0, len(vlines) - 1))
            row_h = max(END_ROW_H, block + 36)
            row_layouts.append((label, vlines, vsize, y, row_h, line_h))
            y += row_h
        cta_top = None
        if self.cta:
            cta_top = y + SP_L
            y = cta_top + self.pill_height()
        origin = self._end_origin(y, SAFE_TOP)
        self.tag(draw, MX, origin, TAGS['房源'])
        self._paint_name_lines(image, name_lines, name_bases, name_size, origin)
        self.paint_price_plan(image, price_plan, origin + price_base, unit_fill=GREY)
        for i, (label, vlines, vsize, yy, row_h, line_h) in enumerate(row_layouts):
            top = origin + yy
            if i:
                draw.rectangle((MX, top, W - MX, top + 1), fill=HAIR)
            rel0 = vlines[0][2]
            base = top + max(8, (row_h - (line_h * len(vlines) + 8 * (len(vlines) - 1))) // 2) - rel0[1]
            self.draw(draw, (MX, base), label, 'sans', S, GOLD, role='label')
            for j, (text, x, _rel) in enumerate(vlines):
                self.draw(draw, (x, base + j * (line_h + 8)), text, 'sans', vsize, INK, role='value')
        if cta_top is not None:
            self.tag(draw, MX, origin + cta_top, self.cta)
        return image

    def _end_editorial(self):
        """Kicker, name, price, then a two-column label-over-value grid."""
        image = Image.new('RGB', (W, H), BLACK)
        draw = ImageDraw.Draw(image)
        rows = self.end_rows()
        name = self.community or '精选好房'
        name_size, name_lines = self._title_block(name, MX, W - SAFE)
        price_plan = self.plan_price(MX, W - SAFE)
        kicker = '房源信息'
        t, b = self.ink(kicker, 'sans', S)
        kicker_base = -t
        y = (b - t) + SP_S
        name_bases, name_bottom = self._line_bases(name_lines, y, 12)
        y = name_bottom + SP_M
        price_base = y - price_plan['above']
        y = price_base + price_plan['below'] + SP_L
        rule_y = y
        y += 2 + SP_M
        left, right_limit = MX, W - SAFE
        col_w = (right_limit - left - SP_L) // 2
        xs = [left, left + col_w + SP_L]
        prepared = []
        for label, value in rows:
            vsize, vlines = self.fit_lines(value, 'sans', M, MIN_TEXT, left + col_w, prefer_x=left)
            lt, lb = self.ink(label, 'sans', S)
            label_h = lb - lt
            if vlines:
                vh = vlines[0][2][3] - vlines[0][2][1]
                value_h = vh * len(vlines) + 6 * (len(vlines) - 1)
            else:
                vh, value_h = 0, 0
            prepared.append((label, value, vsize, vlines, label_h, value_h, vh))
        pairs = []
        i = 0
        while i < len(prepared):
            pair = prepared[i:i + 2]
            row_h = max(item[4] + 10 + item[5] for item in pair) + SP_S
            pairs.append((pair, y, row_h))
            y += row_h
            i += 2
        origin = self._end_origin(y, SAFE)
        self._paint_kicker(draw, MX, origin + kicker_base, kicker)
        self._paint_name_lines(image, name_lines, name_bases, name_size, origin)
        self.paint_price_plan(image, price_plan, origin + price_base, unit_fill=GOLD)
        draw.rectangle((MX, origin + rule_y, W - SAFE, origin + rule_y + 2), fill=GOLD)
        for pair, yy, _row_h in pairs:
            for col, item in enumerate(pair):
                label, value, _vsize, _vlines, label_h, _value_h, _vh = item
                x = xs[col]
                top = origin + yy
                lt, _lb = self.ink(label, 'sans', S)
                self.draw(draw, (x, top - lt), label, 'sans', S, GOLD, role='label')
                vsize, vlines = self.fit_lines(value, 'sans', M, MIN_TEXT, x + col_w, prefer_x=x)
                vbases, _bottom = self._line_bases(vlines, top + label_h + 10, gap=6)
                for (text, vx, _rel), base in zip(vlines, vbases):
                    self.draw(draw, (vx, base), text, 'sans', vsize, INK, role='value')
        return image

    def _end_poster(self):
        """Centred stack: block, name, price, then one centred fact line per row."""
        image = Image.new('RGB', (W, H), BLACK)
        draw = ImageDraw.Draw(image)
        rows = self.end_rows()
        name = self.community or '精选好房'
        name_size, name_lines = self._title_block(name, SAFE, W - SAFE)
        name_lines = [(text, self._center_x(rel), rel) for text, _x, rel in name_lines]
        price_plan = self.plan_price(SAFE, W - SAFE, force_stack=True, align='center')
        tag_h = self.pill_height(S)
        y = tag_h + SP_M
        name_bases, name_bottom = self._line_bases(name_lines, y, 12)
        y = name_bottom + SP_S
        price_base = y - price_plan['above']
        y = price_base + price_plan['below'] + SP_L
        rule_y = y
        y += 2 + SP_M
        facts = []
        for label, value in rows:
            text = f'{label}    {value}'
            fsize, flines = self.fit_lines(text, 'sans', M, MIN_TEXT, W - SAFE, prefer_x=SAFE)
            flines = [(line, self._center_x(rel), rel) for line, _x, rel in flines]
            bases, bottom = self._line_bases(flines, y, gap=8)
            facts.append((flines, fsize, bases))
            y = bottom + SP_S
        origin = self._end_origin(y, SAFE)
        self._paint_tag_centered(draw, origin, TAGS['房源'])
        self._paint_name_lines(image, name_lines, name_bases, name_size, origin)
        self.paint_price_plan(image, price_plan, origin + price_base, unit_fill=GOLD)
        mid = W // 2
        draw.rectangle((mid - 90, origin + rule_y, mid + 90, origin + rule_y + 2), fill=GOLD)
        for flines, fsize, bases in facts:
            for (text, x, _rel), base in zip(flines, bases):
                self.draw(draw, (x, origin + base), text, 'sans', fsize, INK, role='value')
        return image

    def _end_ledger(self):
        """Rail, name, right-aligned price, then a gold label block on every row."""
        image = Image.new('RGB', (W, H), BLACK)
        draw = ImageDraw.Draw(image)
        rows = self.end_rows()
        text_x = SAFE + 36
        name = self.community or '精选好房'
        name_size, name_lines = self._title_block(name, text_x, W - SAFE)
        price_plan = self.plan_price(text_x, W - SAFE, force_stack=True, align='right')
        name_bases, name_bottom = self._line_bases(name_lines, 0, 12)
        y = name_bottom + SP_M
        price_base = y - price_plan['above']
        y = price_base + price_plan['below'] + SP_L
        row_layouts = []
        for label, value in rows:
            label_w = int(self.text_width(label, 'sans', S, tracking=2) + 56)
            vx = text_x + label_w + SP_M
            vsize, vlines = self.fit_lines(value, 'sans', M, MIN_TEXT, W - SAFE, prefer_x=vx)
            label_h = self.pill_height(S)
            if vlines:
                vh = vlines[0][2][3] - vlines[0][2][1]
                value_h = vh * len(vlines) + 8 * (len(vlines) - 1)
            else:
                value_h = label_h
            row_h = max(label_h, value_h) + 24
            row_layouts.append((label, label_w, label_h, vlines, vsize, y, row_h))
            y += row_h
        origin = self._end_origin(max(y, 1), SAFE)
        draw.rectangle((SAFE, origin, SAFE + 8, origin + y), fill=GOLD)
        self._paint_name_lines(image, name_lines, name_bases, name_size, origin)
        self.paint_price_plan(image, price_plan, origin + price_base, unit_fill=GOLD)
        for label, label_w, label_h, vlines, vsize, yy, row_h in row_layouts:
            top = origin + yy
            tag_top = top + max(0, (row_h - label_h) // 2)
            self.tag(draw, text_x, tag_top, label)
            if not vlines:
                continue
            rel0 = vlines[0][2]
            line_h = rel0[3] - rel0[1]
            block = line_h * len(vlines) + 8 * (len(vlines) - 1)
            base = top + max(0, (row_h - block) // 2) - rel0[1]
            for j, (text, x, _rel) in enumerate(vlines):
                self.draw(draw, (x, base + j * (line_h + 8)), text, 'sans', vsize, INK, role='value')
        return image

    def audit_text_bounds(self):
        """Record every text box and flag anything past the canvas or the safe inset."""
        self.text_boxes = []
        self._capture = True
        try:
            for shot in self.shots:
                if shot['kind'] == 'end':
                    self.plate_end()
                else:
                    image = Image.new('RGB', (W, H), BLACK)
                    self.paint_text(image, shot, self.band_layout(shot))
        finally:
            self._capture = False
        violations = []
        for box in self.text_boxes:
            l, t, r, b = box['left'], box['top'], box['right'], box['bottom']
            reasons = []
            if l < 0 or t < 0 or r > W or b > H:
                reasons.append('canvas')
            if l < SAFE or t < SAFE or r > W - SAFE or b > H - SAFE:
                reasons.append('safe')
            minimum = MIN_TITLE if box['role'] in ('title', 'price') else MIN_TEXT
            if box['size'] < minimum:
                reasons.append('min-size')
            if reasons:
                item = dict(box)
                item['violation'] = '+'.join(reasons)
                violations.append(item)
        status = 'PASS' if not violations else 'FAIL'
        return {'status': status, 'count': len(self.text_boxes), 'safe': SAFE,
                'violations': violations}

    def plate(self, shot):
        key = (shot.get('plate'), tuple(shot.get('files') or ()))
        if key not in self.plates:
            kind = shot['kind']
            if kind in ('band', 'collage'):
                self.plates[key] = self.compose(shot, None)
            else:
                self.plates[key] = self.plate_end()
        return self.plates[key]

    def locate(self, time):
        if not self.shots:
            return {'kind': 'end', 'dur': 1}, 0
        if time >= self.duration:
            time = max(0, self.duration - 1e-4)
        acc = 0.0
        for shot in self.shots:
            if time < acc + shot['dur'] or shot is self.shots[-1]:
                return shot, max(0.0, time - acc)
            acc += shot['dur']
        return self.shots[-1], 0.0

    def fade(self, plate, local):
        if local >= FADE:
            return plate
        alpha = local / FADE
        alpha = alpha * alpha * (3 - 2 * alpha)
        if alpha <= 0:
            return self.black
        return Image.blend(self.black, plate, alpha)

    def frame(self, time):
        """Frame-accurate: each cut k sits at the start of shot k+1 and its
        transition spans [cut - d/2, cut + d/2], so total duration is unchanged."""
        if not self.shots:
            return self.black
        time = min(max(0.0, time), max(0.0, self.duration - 1e-4))
        i = len(self.starts) - 1
        while i > 0 and time < self.starts[i]:
            i -= 1
        local = time - self.starts[i]
        if i > 0 and self.cuts[i - 1]['dur'] > 0 and local < self.cuts[i - 1]['dur'] / 2:
            k = i - 1
        elif i < len(self.cuts) and self.cuts[i]['dur'] > 0 and \
                time >= self.starts[i + 1] - self.cuts[i]['dur'] / 2:
            k = i
        else:
            k = None
        if k is None:
            image = self.shot_frame(i, local, self._pulse_zoom(time, self.shots[i]))
        else:
            cut = self.cuts[k]
            p = (time - (self.starts[k + 1] - cut['dur'] / 2)) / cut['dur']
            a = self.shot_frame(k, time - self.starts[k])
            b = self.shot_frame(k + 1, time - self.starts[k + 1])
            image = self.transition(cut['type'], a, b, min(1.0, max(0.0, p)), cut)
        # v7: no fade-up from black, and no text fade on shot 1. Frame 0 is the cover.
        return image

    def repair_weak_transitions(self, fallbacks=None, rounds=3):
        """Deterministic fix-up: a cut whose mid frame fails the visibility proof
        (e.g. glitch between two near-identical white rooms) is swapped for the next
        strong effect. Keeps duration, so timing / music sync are untouched.
        Replacements stay inside this template's transition family.
        """
        if fallbacks is None:
            pool = [name for name in self.transition_pool if name not in DISSOLVE_KINDS]
            fallbacks = tuple(pool or self.transition_pool)
        log = []
        for _ in range(rounds):
            bad = [k for k, pr in enumerate(self.transition_proof()) if not pr.get('ok')]
            if not bad:
                break
            for k in bad:
                cut = self.cuts[k]
                old = cut['type']
                prev_t = self.cuts[k - 1]['type'] if k > 0 else None
                next_t = self.cuts[k + 1]['type'] if k + 1 < len(self.cuts) else None
                options = [f for f in fallbacks if f != old and f not in (prev_t, next_t)] or \
                    [f for f in fallbacks if f != old]
                tried = cut.setdefault('_tried', [old])
                options = [f for f in options if f not in tried] or options
                new = options[0]
                tried.append(new)
                if not hasattr(self, 'cut_overrides'):
                    self.cut_overrides = {}
                self.cut_overrides[k] = new
                cut.update(type=new, dir=None, sfx=sfx_tools.sfx_for(new), dissolve=new in DISSOLVE_KINDS,
                           mid_alpha=0.5 if new in DISSOLVE_KINDS else None)
                cut['dur'] = max(cut['dur'], TRANSITION_FLOOR.get(new, 0.32))
                self.shots[k]['transition_out'] = new
                self.shots[k]['transition_dir'] = None
                log.append(f'cut{k + 1:02d} {old} -> {new}')
        for cut in self.cuts:
            cut.pop('_tried', None)
        return log

    def transition_proof(self):
        """Mean absolute difference (0–255) of each mid-transition frame vs both sides.

        Non-dissolves must clear 18. Dissolves (fade, zoom-dissolve) must sit at
        blend weight 0.45–0.55. Also returns an md5 of the raw mid frame.
        """
        proofs = []
        fps = max(1, self.fps)
        for k, cut in enumerate(self.cuts):
            kind = cut['type']
            dur = float(cut['dur'])
            t = float(cut['time'])
            if dur <= 0:
                proofs.append(dict(index=k, type=kind, time=t, dur=dur, ok=False,
                                   reason='hard cut'))
                continue
            t_a = max(0.0, t - dur / 2 - 1.0 / fps)
            t_m = min(max(0.0, self.duration - 1e-4), t)
            t_b = min(max(0.0, self.duration - 1e-4), t + dur / 2 + 1.0 / fps)
            A = np.asarray(self.frame(t_a), np.float32)
            M = np.asarray(self.frame(t_m), np.float32)
            B = np.asarray(self.frame(t_b), np.float32)
            da = float(np.mean(np.abs(A - M)))
            db = float(np.mean(np.abs(B - M)))
            diff = B - A
            den = float(np.sum(diff * diff)) + 1e-6
            alpha = float(np.sum((M - A) * diff) / den)
            dissolve = kind in DISSOLVE_KINDS
            if dissolve:
                ok = 0.45 <= alpha <= 0.55
                reason = 'dissolve-alpha' if ok else 'dissolve-alpha out of range'
            else:
                ok = da > 18.0 and db > 18.0
                reason = 'pixel-diff' if ok else 'pixel-diff below 18'
            raw = np.clip(M, 0, 255).astype(np.uint8).tobytes()
            proofs.append(dict(
                index=k, type=kind, dir=cut.get('dir'), time=round(t, 4), dur=round(dur, 4),
                diff_from_a=round(da, 2), diff_from_b=round(db, 2),
                mid_alpha=None if not dissolve else round(alpha, 4),
                designed_mid_alpha=0.5 if dissolve else None,
                mid_md5=hashlib.md5(raw).hexdigest(),
                ok=bool(ok), reason=reason,
            ))
            print(f"  proof {k} {kind}@{t:.2f} |A-mid|={da:.1f} |B-mid|={db:.1f} "
                  f"α={alpha:.3f} {'OK' if ok else 'FAIL'}", flush=True)
        return proofs

    def still(self, kind):
        for shot in self.shots:
            if shot.get('plate') == kind or shot.get('kind') == kind:
                if kind == 'band' and shot.get('plate') not in (None, 'bed_single', 'com_single'):
                    continue
                return self.plate(shot)
        return None


# ---- No-LLM input resolution ------------------------------------------------
ROOM_WORDS = ('客厅', '卧室', '厨房', '卫生间', '阳台', '餐厅', '书房', '其他')


def _classify_image(name):
    """Role/room from a file name like 02_客厅_1.jpg or 41_房源_..._VR_封面.jpg."""
    if 'VR' in name or 'vr' in name:
        return 'vr_cover', ''
    if '户型' in name:
        return 'floorplan', '户型'
    if '小区' in name:
        return 'community', '小区'
    for room in ROOM_WORDS:
        if room in name:
            return 'room', room
    return 'room', '其他'


def _scan_images(folder):
    exts = {'.jpg', '.jpeg', '.png', '.webp'}
    out = []
    for path in sorted(Path(folder).iterdir()) if Path(folder).is_dir() else []:
        if path.suffix.lower() in exts and path.is_file():
            role, room = _classify_image(path.name)
            out.append({'path': str(path), 'role': role, 'room': room,
                        'label': {'community': '小区环境', 'floorplan': '户型图'}.get(role, room)})
    return out


def resolve_inputs(args):
    """Fill listing/manifest/media/output from --house-dir and normalise both files.

    listing.json missing -> minimal listing from the folder name + manifest/title fields.
    manifest without ordered_images (e.g. a plain list of {file,url}) -> rebuilt by
    classifying the image file names. Nothing here is specific to one listing.
    """
    house = args.house_dir
    if house is not None:
        house = Path(house)
        if not house.is_dir():
            raise FileNotFoundError(f'--house-dir not found: {house}')
        args.listing = args.listing or house / 'listing.json'
        args.manifest = args.manifest or house / 'manifest.json'
        if args.media_dir is None:
            args.media_dir = house / 'images' if (house / 'images').is_dir() else house
    if args.media_dir is None:
        raise ValueError('Give --house-dir or --media-dir')
    listing = {}
    if args.listing and Path(args.listing).is_file():
        listing = json.loads(Path(args.listing).read_text())
    manifest = {}
    if args.manifest and Path(args.manifest).is_file():
        manifest = json.loads(Path(args.manifest).read_text())
    if isinstance(manifest, list):
        manifest = {'files': manifest}
    if not manifest.get('ordered_images'):
        imgs = _scan_images(args.media_dir)
        # also pull community shots from raw/ when the media folder has none
        if house is not None and not any(i['role'] == 'community' for i in imgs):
            imgs += [i for i in _scan_images(house / 'raw') if i['role'] == 'community'][:6]
        manifest['ordered_images'] = imgs
        print(f'Manifest rebuilt from file names: {len(imgs)} images', flush=True)
    for key in ('listing_id', 'community', 'title', 'price', 'layout', 'area_sqm', 'district',
                'bizcircle', 'city'):
        if not listing.get(key) and manifest.get(key):
            listing[key] = manifest[key]
    if not listing.get('listing_id'):
        m = re.search(r'(\d{6,})', str(house or args.media_dir))
        listing['listing_id'] = m.group(1) if m else 'listing'
    if not listing.get('community'):
        listing['community'] = (listing.get('title') or '').split(' ')[0] or '精选好房'
    template, seed = resolve_template_name(getattr(args, 'template', None) or 'gold_classic',
                                           getattr(args, 'seed', None), listing.get('listing_id'))
    args.template = template
    args.seed = seed
    if args.output is None:
        if house is None:
            raise ValueError('Give --output (or --house-dir for the default path)')
        args.output = house / 'video' / f"{listing_slug(listing)}_{listing['listing_id']}_9x16_{template}.mp4"
    return listing, manifest


def listing_slug(listing):
    """ASCII slug: pinyin of the community name when pypinyin exists, else 'house'."""
    name = str(listing.get('community') or '')
    try:
        from pypinyin import lazy_pinyin
        text = ''.join(lazy_pinyin(name))
    except Exception:
        text = name
    text = re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')
    return text or 'house'


def guard_reel_duration(duration, parser, detail=''):
    """Keep the 20s cap. A total under 15s is missing shots, not a hard failure.

    Per-shot dur_lo/dur_hi checks stay with the caller. When those pass and the
    only problem is the reel landing under 15s, warn and continue rendering.
    """
    if duration > 20.0:
        parser.error(f'Duration {duration:.3f}s is outside 15–20s{detail}')
    if duration < 15.0:
        print(
            f'Warning: duration {duration:.3f}s is under 15s because of '
            f'insufficient shots/material; continuing render.',
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--house-dir', type=Path, default=None,
                        help='Listing folder (listing.json / manifest.json / images). Fills the four paths below.')
    for name in ('media-dir', 'listing', 'manifest', 'output'):
        parser.add_argument('--' + name, type=Path, default=None)
    parser.add_argument('--out', dest='output', type=Path, default=None, help='Alias of --output.')
    parser.add_argument('--mode', choices=['magazine'], default='magazine')
    parser.add_argument('--width', type=int, default=1080)
    parser.add_argument('--height', type=int, default=1920)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--bgm', default='auto',
                        help="auto|yes (seeded random bgm/user, else bgm/library), no, "
                             "a folder (pick by --bgm-track or rotation), or an audio file")
    parser.add_argument('--bgm-file', type=Path, default=None, help='Legacy alias: explicit audio file.')
    parser.add_argument('--bgm-track', default=None, help='Track name/slug substring inside the folder.')
    parser.add_argument('--bgm-start', default='auto',
                        help="'auto' = soft melodic phrase (not a chorus drop), or seconds.")
    parser.add_argument('--bgm-volume', type=float, default=0.75,
                        help='Gain after loudness normalisation. v8 default is a little under 1.')
    parser.add_argument('--bgm-lufs', type=float, default=-14.0, help='Loudness target (EBU R128).')
    parser.add_argument('--beat-sync', choices=['on', 'off'], default='on',
                        help='Snap cuts onto phrase onsets / bar lines (±0.40 s). Kicks are not targets.')
    parser.add_argument('--beat-pulse', choices=['on', 'off'], default='off',
                        help='Off by default. Opt in for a 1–2 frame photo zoom on strong beats.')
    parser.add_argument('--listing-type', choices=['auto', 'sale', 'new', 'rent'], default='auto',
                        help='Shot order. auto: new-home flag → new, rent price / 租 → rent, else sale.')
    parser.add_argument('--seed', type=int, default=None,
                        help='Template, transition and default BGM RNG seed. Default: stable hash of the listing id.')
    parser.add_argument('--template', default='gold_classic',
                        help='Visual preset: ' + ', '.join(TEMPLATE_ORDER) + ', or random.')
    parser.add_argument('--text-bounds', choices=['warn', 'strict'], default='warn',
                        help='strict exits non-zero when any text box leaves the canvas or the 60px safe area.')
    parser.add_argument('--sfx', choices=['on', 'off'], default='on',
                        help='Mix a matching transition sound under the BGM.')
    parser.add_argument('--sfx-volume', type=float, default=0.40,
                        help='Linear gain of transition SFX. Kept audible over the softer BGM bed.')
    parser.add_argument('--cta', default='')
    parser.add_argument('--font', default=SERIF_PATH, help='Title serif. Body stays Noto Sans CJK SC.')
    parser.add_argument('--target-size-mb', type=float, default=6,
                        help='Decimal-MB budget used as the VBV maxrate cap (0 = uncapped CRF).')
    parser.add_argument('--crf', type=float, default=21, help='x264 CRF quality target (lower = better).')
    parser.add_argument('--preset', default='medium', help='x264 preset.')
    parser.add_argument('--kenburns', choices=['on', 'off'], default='on',
                        help='Slow camera move on single photos / collage lead tile.')
    parser.add_argument('--kb-strength', type=float, default=0.08,
                        help='Ken Burns zoom amount (0.08 = 1.00->1.08).')
    parser.add_argument('--transitions', default='random',
                        help="random (default, seeded, no immediate repeat, no shake), auto (v6 rotation), "
                             "or a comma list. Names: " + ','.join(sorted(TRANSITIONS)))
    parser.add_argument('--transition-duration', type=float, default=0.40,
                        help='Cap in seconds. Random effects stay in 0.32–0.40s and are never hard cuts.')
    args = parser.parse_args()
    if min(args.width, args.height, args.fps) <= 0 or args.width % 2 or args.height % 2:
        parser.error('Dimensions must be positive even numbers; fps must be positive.')
    for path in (args.font, SANS_PATH, SANS_BOLD_PATH):
        if not Path(path).is_file():
            parser.error(f'Font missing: {path}')

    try:
        listing, manifest = resolve_inputs(args)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    try:
        magazine = Magazine(listing, load_assets(manifest, args.media_dir), args.font, args.cta,
                            kenburns=args.kenburns == 'on', kb_strength=args.kb_strength,
                            transitions=args.transitions, transition_dur=args.transition_duration,
                            listing_type=args.listing_type, seed=args.seed,
                            beat_pulse=args.beat_pulse == 'on', fps=args.fps,
                            template=args.template)
    except ValueError as exc:
        parser.error(str(exc))
    if magazine.duration <= 0:
        parser.error('No sections to render.')
    got = slot_sequence(magazine.shots)
    want = [s for s in SHOT_ORDER[magazine.listing_type]
            if any(sh.get('slot') == s for sh in magazine.shots)]
    if got != want:
        parser.error(f'Shot order {got} does not match the {magazine.listing_type} table {want}')
    if (magazine.groups.get('community') and SHOT_ORDER[magazine.listing_type][0] == 'community'
            and (not magazine.shots or magazine.shots[0].get('slot') != 'community'
                 or not magazine.shots[0].get('hero'))):
        parser.error('Opening shot must be the cover-styled 小区展示 page (title + price).')
    repaired = magazine.repair_weak_transitions()
    for item in repaired:
        print(f"Transition repaired: {item}", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # ---- BGM: choose track, find climax, cut + loudness-normalise ----------
    bgm_info, bgm_wav = None, None
    choice = 'file' if args.bgm_file else args.bgm.strip()
    if choice.lower() in ('no', 'off', 'none'):
        guard_reel_duration(magazine.duration, parser, '; insufficient or excessive material')
    if choice.lower() not in ('no', 'off', 'none'):
        try:
            if args.bgm_file:
                track = {'path': str(args.bgm_file), 'title': args.bgm_file.stem}
            elif choice.lower() in ('auto', 'yes'):
                user_tracks = bgm_tools.list_tracks(BGM_USER)
                if user_tracks:
                    folders = [BGM_USER]
                    print(f'BGM source: bgm/user ({len(user_tracks)} tracks)', flush=True)
                else:
                    folders = [BGM_LIBRARY]
                    print('BGM source: bgm/user has no audio; using bgm/library', flush=True)
                prefer = SOFT_BGM if not args.bgm_track and folders == [BGM_LIBRARY] else None
                track = bgm_tools.pick_track(folders, args.bgm_track, listing.get('listing_id'),
                                             prefer=prefer, seed=magazine.seed)
            elif Path(choice).is_dir():
                track = bgm_tools.pick_track([Path(choice)], args.bgm_track, listing.get('listing_id'))
            elif Path(choice).is_file():
                track = {'path': choice, 'title': Path(choice).stem}
            else:
                parser.error(f'--bgm: not a file or folder: {choice}')
        except FileNotFoundError as exc:
            parser.error(str(exc))
        print(f"BGM chosen: {track['path']} (title={track['title']}, seed={magazine.seed})", flush=True)
        if args.bgm_start == 'auto':
            # Score a ~17.6s phrase, with headroom so a slightly longer edit
            # still starts on the same onset.
            seg = bgm_tools.find_phrase_cached(track['path'], 17.6, headroom=2.6)
        else:
            total = bgm_tools.probe_duration(track['path'])
            length = magazine.duration
            start = max(0.0, min(float(args.bgm_start), max(0.0, total - length)))
            seg = dict(start=start, end=start + length, beats=[], downbeats=[], phrase_onsets=[],
                       tempo=0.0, rank=None, total=total, looped=total < length, engine='manual',
                       mood='manual', reason='--bgm-start was set explicitly')
        magazine.strong_beats = list(seg.get('strong_beats') or [])
        magazine.downbeats = list(seg.get('downbeats') or [])
        magazine.phrase_onsets = list(seg.get('phrase_onsets') or [])
        magazine.beat_times = list(seg.get('beats') or [])
        magazine.fps = args.fps
        # Default off. An explicit --beat-pulse on still needs detected beats.
        magazine.beat_pulse = args.beat_pulse == 'on' and bool(magazine.strong_beats)
        phrase_offset = 0.0
        if args.beat_sync == 'on' and (seg.get('downbeats') or seg.get('phrase_onsets')):
            phrase_offset = magazine.align_to_phrase(seg.get('downbeats') or [],
                                                    seg.get('phrase_onsets') or [],
                                                    window=0.40, offset_limit=0.40)
        playback_start = float(seg['start']) + float(phrase_offset)
        if phrase_offset:
            def _shift(times):
                return [round(float(t) - phrase_offset, 4) for t in times
                        if float(t) - phrase_offset >= -1e-3]
            # downbeats / phrase_onsets were already rewritten in video time.
            magazine.beat_times = _shift(magazine.beat_times)
            magazine.strong_beats = _shift(magazine.strong_beats)
        for shot in magazine.shots:
            lo, hi = shot.get('dur_lo'), shot.get('dur_hi')
            if lo is not None and (shot['dur'] < lo - 0.021 or shot['dur'] > hi + 0.021):
                parser.error(f"{shot_label(shot)} duration {shot['dur']:.3f}s outside {lo}–{hi}")
        guard_reel_duration(magazine.duration, parser)
        bgm_wav = args.output.with_suffix('.bgm.wav')
        stats = bgm_tools.cut_segment(track['path'], playback_start, magazine.duration, bgm_wav,
                                      lufs=args.bgm_lufs, gain=args.bgm_volume,
                                      fade_in=0.08, fade_out=1.15, loop=seg.get('looped', False))
        bgm_info = {k: track.get(k) for k in ('title', 'artist', 'slug', 'path', 'source_page', 'license')}
        bgm_info['user_library_fallback'] = (
            choice.lower() in ('auto', 'yes') and not bgm_tools.list_tracks(BGM_USER))
        bgm_info.update(start=round(playback_start, 3),
                        end=round(playback_start + magazine.duration, 3),
                        tempo=seg.get('tempo'), energy_rank=seg.get('rank'),
                        candidates=seg.get('candidates'), engine=seg.get('engine'),
                        source_lufs=stats['input_lufs'], target_lufs=args.bgm_lufs,
                        beat_sync=args.beat_sync == 'on' and bool(seg.get('downbeats') or seg.get('phrase_onsets')),
                        mood=seg.get('mood'),
                        phrase_onset=seg.get('start'),
                        phrase_offset=round(float(phrase_offset), 3),
                        phrase_reason=seg.get('reason'), phrase_rise=seg.get('phrase_rise'),
                        phrase_sustain=seg.get('phrase_sustain'), bar_index=seg.get('bar_index'),
                        phrase_onsets=magazine.phrase_onsets, snap_window=0.40,
                        volume=args.bgm_volume)
        print(f"BGM: {bgm_info['title']} play {bgm_info['start']:.2f}-{bgm_info['end']:.2f}s "
              f"(phrase onset {seg.get('start')}s, offset {phrase_offset:+.2f}s, "
              f"tempo {bgm_info['tempo']})", flush=True)
        if seg.get('reason'):
            print(f"Phrase: {seg['reason']}", flush=True)

    sfx_info = None
    if args.sfx == 'on':
        events = [{'time': cut['time'], 'id': cut['sfx'], 'transition': cut['type'],
                   'dir': cut.get('dir')}
                  for cut in magazine.cuts if cut.get('sfx') and cut.get('dur', 0) > 0]
        if events:
            if bgm_wav is None:
                bgm_wav = args.output.with_suffix('.bgm.wav')
                sfx_tools.write_silence(bgm_wav, magazine.duration)
            mixed = args.output.with_suffix('.mix.wav')
            sfx_info = sfx_tools.mix_under(bgm_wav, events, mixed, volume=args.sfx_volume)
            if bgm_wav.exists() and bgm_wav != mixed:
                bgm_wav.unlink()
            bgm_wav = mixed
            print(f"SFX: {len(sfx_info['events'])} hits @ volume {args.sfx_volume:g}, "
                  f"mix peak {sfx_info['peak']}, sfx peak {sfx_info['sfx_peak']}", flush=True)

    names = [name for shot in magazine.shots for name in (shot.get('files') or [])]
    if len(names) != len(set(names)):
        parser.error(f'Duplicate photos in the timeline: {names}')
    if str(args.transitions).strip().lower() in {'random', 'rand'}:
        banned = [c['type'] for c in magazine.cuts if c['type'] in {'shake', 'cut'} or c['dur'] <= 0]
        if banned:
            parser.error(f'Random transitions included a hard cut or shake: {banned}')
    print(f"Template: {magazine.template_name} seed {magazine.seed}", flush=True)
    print(f"Order ({magazine.listing_type}, seed {magazine.seed}, {magazine.duration:.2f}s): "
          + ' → '.join(
              f"{shot_label(s)} {s['dur']:.2f}s[{','.join(s.get('files') or [])}]"
              for s in magazine.shots), flush=True)
    if magazine.skipped:
        print('Skipped duplicates: ' + ' | '.join(magazine.skipped), flush=True)
    print('Cuts: ' + ', '.join(
        f"{c['type']}{(':' + c['dir']) if c.get('dir') else ''}@{c['time']:.2f}/{c['dur']:.2f}s+{c.get('sfx') or '-'}"
        for c in magazine.cuts), flush=True)
    if magazine.phrase_snaps:
        print('Phrase snaps: ' + ', '.join(
            f"{s['hit']}@{s['time']:.2f}(Δ{s['delta']:+.2f})" for s in magazine.phrase_snaps), flush=True)

    def resized(image):
        if image.size == (args.width, args.height):
            return image
        return image.resize((args.width, args.height), Image.Resampling.LANCZOS)

    stem = args.output.stem
    open_shot = magazine.shots[0] if magazine.shots else None
    bed_shot = end_shot = None
    for shot in magazine.shots:
        if shot.get('plate') in ('bed_collage', 'bed_single'):
            if bed_shot is None or shot.get('plate') == 'bed_collage':
                bed_shot = shot
        if shot.get('kind') == 'end':
            end_shot = shot
    for label, shot in (('open', open_shot), ('bedrooms', bed_shot), ('end', end_shot)):
        if shot is not None:
            resized(magazine.plate(shot)).save(args.output.with_name(f'{stem}_{label}.png'))

    # CRF quality with a VBV cap derived from the decimal-MB budget (~8% kept for
    # the container and the AAC track). Single delivery file.
    if args.target_size_mb > 0:
        bitrate = int((args.target_size_mb * 1_000_000 * 8 / magazine.duration * 0.92 - 96000) / 1000)
        bitrate = max(300, min(12000, bitrate))
    else:
        bitrate = 0
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{args.width}x{args.height}', '-r', str(args.fps), '-i', 'pipe:0']
    if bgm_wav:
        # Segment is already trimmed, loudness-normalised and faded (bgm_tools).
        cmd += ['-i', str(bgm_wav), '-map', '0:v:0', '-map', '1:a:0', '-c:a', 'aac', '-b:a', '128k']
    else:
        cmd += ['-an']
    cmd += ['-t', f'{magazine.duration:.3f}', '-c:v', 'libx264', '-preset', args.preset, '-threads', '4',
            '-crf', f'{args.crf:g}']
    if bitrate:
        cmd += ['-maxrate', f'{bitrate}k', '-bufsize', f'{bitrate * 2}k']
    cmd += ['-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(args.output)]
    bounds = magazine.audit_text_bounds()
    magazine.bounds_report = bounds
    print(f"text bounds check: {bounds['status']}, {bounds['count']} boxes", flush=True)
    for item in bounds['violations']:
        print(f"WARNING text bounds: {item['violation']} {item['role']} size={item['size']} "
              f"box=({item['left']},{item['top']},{item['right']},{item['bottom']}) {item['text']}",
              flush=True)
    if bounds['violations'] and args.text_bounds == 'strict':
        parser.error(
            f"text bounds check FAIL, {len(bounds['violations'])} boxes outside the canvas or safe area")
    print('Transition proof:', flush=True)
    proofs = magazine.transition_proof()
    failed = [p for p in proofs if not p.get('ok')]
    if failed:
        parser.error('Transition proof failed: ' + ', '.join(
            f"{p['type']}@{p.get('time')} {p.get('reason')}" for p in failed))
    cover = np.asarray(magazine.frame(0.0), np.float32)
    cover_luma = float(cover.mean())
    if cover_luma < 25:
        parser.error(f'Frame 0 looks black (mean luma {cover_luma:.1f})')
    print(f'Frame 0 mean luma {cover_luma:.1f} (cover, not a black start)', flush=True)
    print(f'Rendering {magazine.duration:.1f}s, {args.width}×{args.height}, crf {args.crf:g}, '
          f'cap {bitrate or "none"} kbps', flush=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frames = round(magazine.duration * args.fps)
    try:
        for i in range(frames):
            proc.stdin.write(resized(magazine.frame(i / args.fps)).tobytes())
            if i % (args.fps * 3) == 0:
                print(f'  {i / args.fps:.0f}/{magazine.duration:.0f}s', flush=True)
        proc.stdin.close()
        if proc.wait():
            raise RuntimeError('ffmpeg encoding failed')
    except BaseException:
        proc.kill()
        proc.wait()
        raise

    payload = {
        'duration': magazine.duration,
        'width': args.width,
        'height': args.height,
        'fps': args.fps,
        'listing_type': magazine.listing_type,
        'template': magazine.template_name,
        'seed': magazine.seed,
        'text_bounds': getattr(magazine, 'bounds_report', None),
        'order': [shot_label(s) for s in magazine.shots],
        'sections': magazine.sections,
        'shots': [{'kind': s['kind'], 'plate': s.get('plate'), 'slot': s.get('slot'),
                   'name': shot_label(s), 'label': s.get('label'), 'hero': bool(s.get('hero')),
                   'title': s.get('title'), 'start': None, 'duration': s['dur'],
                   'dur_lo': s.get('dur_lo'), 'dur_hi': s.get('dur_hi'),
                   'files': list(s.get('files') or []),
                   'kenburns': s.get('kb'), 'kb_strength': round(s.get('kb_strength', 0.0), 4),
                   'transition_out': s.get('transition_out')} for s in magazine.shots],
        'cuts': magazine.cuts,
        'beats': magazine.beat_times,
        'downbeats': magazine.downbeats,
        'phrase_onsets': magazine.phrase_onsets,
        'phrase_snaps': magazine.phrase_snaps,
        'strong_beats': magazine.strong_beats,
        'beat_deltas': magazine.beat_deltas,
        'beat_pulse': bool(magazine.beat_pulse),
        'shake_in_random_pool': 'shake' in RANDOM_POOL,
        'skipped_duplicates': list(magazine.skipped),
        'transition_proof': proofs,
        'bgm': bgm_info,
        'sfx': sfx_info,
        'volume': args.bgm_volume if bgm_info else None,
        'assets': {k: [n for n, _ in v] for k, v in magazine.groups.items()},
    }
    acc = 0.0
    for item, shot in zip(payload['shots'], magazine.shots):
        item['start'] = round(acc, 3)
        acc += shot['dur']
    if bgm_wav and bgm_wav.exists():
        bgm_wav.unlink()
    args.output.with_suffix('.timeline.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    size_mb = args.output.stat().st_size / 1_000_000
    print(f'Done: {args.output} ({size_mb:.2f} MB, {magazine.duration:.1f}s)', flush=True)


if __name__ == '__main__':
    main()
