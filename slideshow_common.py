"""Shared drawing primitives, fonts, template registry and local image loading."""
from __future__ import annotations

import hashlib
import math
import os
import random
import re
from pathlib import Path

import numpy as np

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

def installed_font(bundled, linux, windows):
    candidates = [bundled, Path(linux)]
    if os.name == 'nt':
        candidates.append(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / windows)
    return str(next((p for p in candidates if p.is_file()), candidates[0]))

SERIF_PATH = installed_font(SERIF_BLACK_PATH, SERIF_PATH, 'simsun.ttc')
SANS_BOLD_PATH = installed_font(SANS_BLACK_PATH, SANS_BOLD_PATH, 'msyhbd.ttc')
SANS_PATH = SANS_BOLD_PATH
DEFAULT_BGM = Path(__file__).resolve().parent / 'bgm/soft_ambient_28s.m4a'   # legacy
BGM_LIBRARY = Path(__file__).resolve().parent / 'bgm/library'   # royalty-free, see library.json
BGM_USER = Path(__file__).resolve().parent / 'bgm/user'         # drop your own licensed tracks here
# Library auto-pick stays on the softer phrase tracks. Summer Dream is still
# selectable with --bgm-track, but it is not the default.
SOFT_BGM = ('drawing-the-sky', 'happy-times')

WIN_FONTS_DIR = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'

FONT_PROFILES = {
    'dengxian': {
        'name': '等线极简新风',
        'title': 'Dengb.ttf',
        'body': 'Deng.ttf',
        'desc': '极简现代、克制高级建筑感',
    },
    'heiti': {
        'name': '硬朗黑体商业画报',
        'title': 'simhei.ttf',
        'body': 'msyh.ttc',
        'desc': '粗壮有力、商业冲击力强、醒目突出',
    },
    'yahei': {
        'name': '微软雅黑现代风',
        'title': 'msyhbd.ttc',
        'body': 'msyh.ttc',
        'desc': '清晰干练、数字友好的现代画报感',
    },
    'kaiti': {
        'name': '雅致人文楷体',
        'title': 'simkai.ttf',
        'body': 'msyh.ttc',
        'desc': '笔触温润、东方诗意空间气息',
    },
    'fangsong': {
        'name': '清秀东方仿宋',
        'title': 'simfang.ttf',
        'body': 'Deng.ttf',
        'desc': '清秀雅正、东方文人高雅韵味',
    },
    'songti': {
        'name': '经典典雅宋体',
        'title': 'simsun.ttc',
        'body': 'msyhbd.ttc',
        'desc': '经典大平层尊贵感、衬线品质典范',
    },
    'youyuan': {
        'name': '亲和温润幼圆',
        'title': 'SIMYOU.TTF',
        'body': 'msyh.ttc',
        'desc': '圆润柔和、亲切宜居家庭温馨感',
    },
    'lishu': {
        'name': '古朴厚重隶书',
        'title': 'SIMLI.TTF',
        'body': 'msyh.ttc',
        'desc': '横平竖直汉隶风、稳重大气',
    },
}

def resolve_font_profile(requested=None, seed=None):
    """Resolve font profile. If requested is 'random' or None, draw from available profiles."""
    if requested and Path(requested).is_file():
        p = Path(requested).resolve()
        return {
            'id': 'custom',
            'name': '自定义字体',
            'title_path': str(p),
            'body_path': str(SANS_BOLD_PATH),
            'desc': f'指定字体文件: {p.name}',
        }

    available = {}
    for pid, pdata in FONT_PROFILES.items():
        t_path = WIN_FONTS_DIR / pdata['title']
        b_path = WIN_FONTS_DIR / pdata['body']
        if t_path.is_file() and b_path.is_file():
            available[pid] = {
                'id': pid,
                'name': pdata['name'],
                'title_path': str(t_path),
                'body_path': str(b_path),
                'desc': pdata['desc'],
            }

    if not available:
        return {
            'id': 'default',
            'name': '默认系统字体',
            'title_path': str(SERIF_PATH),
            'body_path': str(SANS_BOLD_PATH),
            'desc': '默认字体配置',
        }

    req_key = str(requested or '').strip().lower()
    if req_key in available:
        return available[req_key]

    # Draw from available font pool ("抽卡")
    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    chosen_id = rng.choice(sorted(available.keys()))
    return available[chosen_id]

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
REFERENCE_TEMPLATES = ('immersive_gold', 'cream_editorial', 'mono_film', 'vermilion_vertical')
TEMPLATE_ORDER = ('gold_classic', 'editorial', 'poster', 'ledger') + REFERENCE_TEMPLATES
# v14 names are deliberately separate: retain the previous review versions.
V14_TEMPLATES = ('v14_cinematic', 'v14_editorial', 'v14_cinema_frame',
                 'v14_vertical', 'v14_price_poster', 'v14_side_ledger',
                 'v14_dual_panel', 'v14_blueprint')
V14_LABELS = ('沉浸金幕', '上图下刊', '宽幕片名', '朱印竖题',
              '价格海报', '左右档案', '双幕分镜', '蓝图手册')
AD_TEMPLATES = ('ad_masthead', 'ad_photo_story')
MOBILE_TEMPLATES = ('v14_editorial',) + AD_TEMPLATES
# Explicit review version: retain the approved production pool and v19 output.
STORY_TEMPLATE = 'ad_photo_story_v20'
DEMO_AB_TEMPLATES = ('tour_route', 'cinema_immersive')
NARRATIVE_TEMPLATES = (STORY_TEMPLATE,) + DEMO_AB_TEMPLATES
MOBILE_LAYOUTS = MOBILE_TEMPLATES + NARRATIVE_TEMPLATES
RECOMMENDED_TEMPLATES = AD_TEMPLATES + NARRATIVE_TEMPLATES
TEMPLATE_ORDER += V14_TEMPLATES + AD_TEMPLATES + NARRATIVE_TEMPLATES
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

for _name in REFERENCE_TEMPLATES:
    TEMPLATES[_name] = {'transitions': ('push', 'wipe', 'zoom', 'slide_left', 'light_leak')}
for _name in V14_TEMPLATES:
    TEMPLATES[_name] = {'transitions': ('push', 'wipe', 'zoom', 'slide_left')}
TEMPLATES['v14_editorial'] = {'transitions': ('slide_left', 'slide_right', 'wipe')}
for _name in AD_TEMPLATES:
    TEMPLATES[_name] = {'transitions': ('slide_left', 'slide_right', 'wipe')}
TEMPLATES[STORY_TEMPLATE] = {'transitions': ('slide_left', 'slide_right', 'wipe')}
for _name in DEMO_AB_TEMPLATES:
    TEMPLATES[_name] = {'transitions': ('slide_left', 'slide_right', 'wipe')}
TEMPLATES['cinema_immersive'] = {'transitions': ('fade', 'slide_left', 'wipe')}


def derived_seed(seed, domain):
    return int.from_bytes(hashlib.sha256(f'{seed}:{domain}'.encode()).digest()[:8], 'big')


def resolve_template_name(requested, seed, listing_id):
    """Return (template, seed); random selects approved mobile layouts; older names stay explicit."""
    requested = str(requested or 'random').strip().lower().replace('-', '_')
    if requested not in TEMPLATES and requested != 'random':
        names = ', '.join(TEMPLATE_ORDER)
        raise ValueError(f'Unknown --template {requested}; choose {names} or random')
    resolved = stable_seed(listing_id, seed)
    if requested == 'random':
        requested = random.Random(resolved).choice(RECOMMENDED_TEMPLATES)
    return requested, resolved


def load_assets(manifest, media):
    groups = {}
    for entry in manifest.get('ordered_images', []):
        name = Path(entry.get('rel_path') or entry.get('path') or '').name
        relative = Path(entry.get('rel_path') or '')
        path = media / name
        if not path.is_file() and relative.parts:
            path = media.parent / relative
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


class TemplateCanvas:
    """Small drawing vocabulary; each v14 template owns its page geometry.

    All photos use contain or a motion-inclusive 82% crop floor. Text never
    generates facts. These primitives have no network or model dependencies.
    """
    def __init__(self, magazine, shot, bg, fg, accent, muted):
        self.m, self.shot = magazine, shot
        self.bg, self.fg, self.accent, self.muted = bg, fg, accent, muted
        self.base = Image.new('RGB', (W,H), bg)
        self.overlay = Image.new('RGBA', (W,H))
        self.draw = ImageDraw.Draw(self.overlay)
        self.photos = shot.get('photos') or ([shot['photo']] if shot.get('photo') else [])
        self.end = shot['kind'] == 'end'
        self.plan = shot.get('label') == '户型'
        self.hero = shot is magazine.shots[0] and not self.end and not self.plan
        self.room = shot.get('label', '')
        if self.room == '封面':
            self.room = next((k for k, ps in magazine.groups.items()
                              if k not in ('community','floorplan') and self.photos
                              and any(p[0] == self.photos[0][0] for p in ps)), '房源')
        self.title = (magazine.community or '房源信息') if self.hero or self.end else ('户型图' if self.plan else self.room)
        self.location = ' · '.join(p for p in (magazine.city,magazine.district,magazine.bizcircle) if p)
        self.price = magazine.price if self.hero or self.end else ''
        self.facts = [v for v in (shot.get('meta') or []) if v]
        if self.hero:
            self.facts = [v for v in (magazine.layout_short,magazine.area,magazine.orientation) if v]
        elif self.plan:
            self.facts = [v for v in (magazine.layout_full,
                          f'建面{magazine.area}' if magazine.area else '',
                          f'套内{magazine.inner_area}' if magazine.inner_area else '') if v]
        elif shot.get('hero'):
            self.facts = magazine._room_facts(self.room)
        self.photo_rects, self.kb, self.boxes = [], [], []

    def rect(self, box, color):
        ImageDraw.Draw(self.base).rectangle(box,fill=color)

    def rule(self, x, y, width, color=None):
        ImageDraw.Draw(self.base).line((x,y,x+width,y),fill=color or self.muted,width=2)

    def text(self, value, box, size=56, color=None, kind='sans', align='left', role='caption', lines=3):
        value = str(value or '').strip()
        x,y,w,h = box
        if not value:
            return y
        # Numbers plus units are atomic; punctuation never starts a fresh line.
        tokens = re.findall(r'\d+(?:[.,]\d+)*(?:元/㎡|元/月|万元|万|㎡|m²|室|厅|厨|卫|层|年|户|%)?|.',value)
        for sz in range(int(size),35,-2):
            font = self.m.font(kind,sz)
            rows, row = [], ''
            for token in tokens:
                if row and font.getlength(row+token)>w-4 and token not in '，。·、）':
                    rows.append(row); row=''
                row += token
            if row: rows.append(row)
            if len(rows)==2 and len(rows[-1])<=2 and not re.search(r'\d',value):
                split=(len(value)+1)//2
                candidate=[value[:split],value[split:]]
                if all(font.getlength(v)<=w-4 for v in candidate): rows=candidate
            bbs=[font.getbbox(v) for v in rows]
            total=sum(bb[3]-bb[1] for bb in bbs)+14*max(0,len(rows)-1)
            if total<=h and len(rows)<=lines and all(bb[2]-bb[0]<=w for bb in bbs):
                break
        else:
            raise ValueError(f'{self.m.template_name}: text does not fit {value!r} in {box}')
        for row,bb in zip(rows,bbs):
            rw,rh=bb[2]-bb[0],bb[3]-bb[1]
            xx=x+(w-rw)//2 if align=='center' else x+w-rw if align=='right' else x
            self.draw.text((xx-bb[0],y-bb[1]),row,font=font,fill=color or self.fg)
            bounds=(xx,y,xx+rw,y+rh)
            self.m._note(bounds,row,role,sz)
            self.boxes.append(dict(text=row,rect=bounds,role=role))
            y+=rh+14
        return y-14

    def name(self, box, size=100, **kw):
        return self.text(self.title,box,size,role='heading',**kw)

    def amount(self, box, size=132, **kw):
        return self.text(self.price,box,size,color=self.accent,role='amount',lines=2,**kw)

    def summary(self, box, size=46, **kw):
        return self.text(dot_join(self.facts[:3]),box,size,color=self.muted,**kw)

    def picture(self, index, box, crop=False, align='center'):
        if index>=len(self.photos): return None
        x,y,w,h=box
        src=self.photos[index][1]
        zoom=min(.03,self.shot.get('kb_strength',0)) if not self.plan else 0
        ratio=src.width/src.height
        retain=min(ratio/(w/h),(w/h)/ratio)/(1+zoom)**2
        if crop and not self.plan and retain>=.82:
            fitted=ImageOps.fit(src,(round(w),round(h)),Image.Resampling.LANCZOS)
        else:
            fitted=ImageOps.contain(src,(round(w),round(h)),Image.Resampling.LANCZOS)
            x+=(w-fitted.width)/2
            y+=0 if align=='top' else h-fitted.height if align=='bottom' else (h-fitted.height)/2
        x,y=round(x),round(y)
        w,h=fitted.size
        self.base.paste(fitted,(x,y))
        self.photo_rects.append((x,y,w,h))
        if self.shot.get('kb') and not self.plan:
            self.kb.append(dict(src=src,rect=(x,y,w,h),move=self.shot['kb'],strength=zoom))
        return x,y,w,h

    def gallery(self, box, mode='lead', indices=None, align='center'):
        ids=list(range(len(self.photos))) if indices is None else list(indices)
        if not ids: return
        x,y,w,h=box; gap=20
        ratios=[self.photos[i][1].width/self.photos[i][1].height for i in ids]
        if len(ids)==1:
            self.picture(ids[0],box,crop=not self.plan,align=align);return
        if mode=='row' or (len(ids)==2 and all(r<1 for r in ratios)):
            hh=(w-gap*(len(ids)-1))/sum(ratios); xx=0; rects=[]
            for r in ratios:
                rects.append((xx,0,hh*r,hh));xx+=hh*r+gap
        elif mode=='columns' and len(ids)>2:
            inv=sum(1/r for r in ratios[1:])
            hh=(w-gap+gap*(len(ids)-2)/inv)/(ratios[0]+1/inv)
            lead=hh*ratios[0]; tail=w-gap-lead
            rects=[(0,0,lead,hh)];yy=0
            for r in ratios[1:]:
                rects.append((lead+gap,yy,tail,tail/r));yy+=tail/r+gap
        elif mode=='stack':
            rects=[]; yy=0
            for r in ratios:
                rects.append((0,yy,w,w/r)); yy+=w/r+gap
        else:
            lead=w/ratios[0]
            lower=(w-gap*(len(ids)-2))/sum(ratios[1:])
            rects=[(0,0,w,lead)];xx=0
            for r in ratios[1:]:
                rects.append((xx,lead+gap,lower*r,lower));xx+=lower*r+gap
        natural=max(yy+hh for xx,yy,ww,hh in rects)
        scale=min(1,h/natural)
        ox=x+(w-w*scale)/2
        oy=y+(0 if align=='top' else h-natural*scale if align=='bottom' else (h-natural*scale)/2)
        for i,(xx,yy,ww,hh) in zip(ids,rects):
            self.picture(i,(ox+xx*scale,oy+yy*scale,ww*scale,hh*scale))

    def table(self, box, columns=1, colored=False):
        rows=self.m.end_rows()
        if not rows:return
        x,y,w,h=box
        count=math.ceil(len(rows)/columns); rh=min(188 if columns>1 else 112,h/count)
        cw=(w-32*(columns-1))/columns
        for i,(label,value) in enumerate(rows):
            xx=x+(i%columns)*(cw+32); yy=y+(i//columns)*rh
            self.rule(xx,yy,cw)
            if columns==1:
                self.text(label,(xx,yy+24,130,rh-30),38,color=self.accent if colored else self.muted,lines=1)
                self.text(value,(xx+158,yy+22,cw-158,rh-28),48,lines=2)
            else:
                self.text(label,(xx,yy+16,cw,44),36,color=self.accent if colored else self.muted,lines=1)
                self.text(value,(xx,yy+68,cw,rh-76),46,lines=2)

    def finish(self):
        text_overlay = self.overlay
        fixed = getattr(self, 'fixed_overlay', None)
        if fixed is not None:
            self.overlay = Image.alpha_composite(fixed, text_overlay)
        rgba=np.asarray(self.overlay);alpha=rgba[...,3:4].astype(np.uint16)
        result = dict(base=self.base,base_np=np.asarray(self.base),
                    tb=(rgba[...,:3].astype(np.uint16)*alpha+127)//255,inv=255-alpha,
                    kb=self.kb,photo_rects=self.photo_rects,layout_boxes=self.boxes,
                    content_bottom=max((v['rect'][3] for v in self.boxes),default=0))
        if hasattr(self, 'text_events'):
            result['text_events'] = [dict(event, image=text_overlay.crop(event['rect']))
                                     for event in self.text_events]
        if fixed is not None:
            result['fixed_overlay'] = fixed
        return result
