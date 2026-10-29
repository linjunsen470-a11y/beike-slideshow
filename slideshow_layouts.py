"""Typography and static template layouts; no IO, networking or encoding."""
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFilter
from PIL import ImageFont
from PIL import ImageOps
from pathlib import Path
import math
import numpy as np
import re
from slideshow_common import (
    AD_TEMPLATES, BLACK, CHIP_GAP, CHIP_SIZE, COLLAGE_LEAD_H,
    COLLAGE_PAIR_H, END_ROW_H, FONT_DIR, GAP, GOLD,
    GOLD_STOPS, GREY, H, HAIR, INK,
    INK_THR, L, M, MIN_TEXT, MIN_TITLE,
    MX, NARRATIVE_TEMPLATES, PILL_PAD_Y, PRICE_SIZE, S,
    SAFE, SAFE_TOP, SP_L, SP_M, SP_S,
    STROKE, TAGS, TAG_GAP, TAG_SIZE, TITLE_OVERLAP,
    TemplateCanvas, UNIT_SIZE, V14_TEMPLATES, W, WHITE_STOPS,
    dot_join, installed_font, sc_index, snap, vgradient,
)

import slideshow_templates


class LayoutRenderer:
    def font(self, kind, size):
        """'serif' = title face (Black if installed); anything else = Sans Black/Bold."""
        key = (kind, size)
        if key not in self.fonts:
            if kind == 'serif':
                path, index = self.serif_path, self.serif_index
            elif kind == 'sansBold':
                path, index = self.sans_bold_path, self.sans_bold_index
            else:
                path, index = self.sans_path, self.sans_index
            self.fonts[key] = ImageFont.truetype(path, int(size), index=index)
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
        style = self.variant['style']
        if style == 1:
            draw.rounded_rectangle(rect, radius=12, outline=fill, width=2)
            ink = fill
        elif style == 2:
            draw.line((rect[0], rect[3]-3, rect[0]+min(width,140), rect[3]-3), fill=fill, width=3)
            ink = fill
        else:
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

    def _contain_shot(self, shot, above, below, prefer_min=SAFE):
        height = self.photo_height(shot)
        if shot['kind'] != 'collage':
            natural = self.resize_w(shot['photo'][1], W).height
            room = H - 2 * SAFE - above - below
            if room >= natural:
                # Optional photo growth must never turn a full-width image
                # into a narrower image just to fit the same typography.
                height = min(height, int(room))
        return self._contain(above, height, below, prefer_min)

    def paint_title(self, image, base, title, size):
        self.fancy(image, (MX, base), title, 'serif', size, WHITE_STOPS, stroke=4, shadow=(0, 8), blur=10)

    def price_lockup(self, image, x, base, size=PRICE_SIZE, unit_size=UNIT_SIZE, force_stack=False,
                     align='left', unit_fill=GREY):
        """Gold-gradient 花字 price. The unit sits beside it, or on the next line."""
        plan = self.plan_price(x, force_stack=force_stack, align=align, price_size=size, unit_size=unit_size)
        return self.paint_price_plan(image, plan, base, unit_fill=unit_fill)

    def paint_photos(self, image, shot, y, width=None, x=None, height=None):
        """Paste the band or collage at y; returns its height.

        Width defaults to the full frame. A narrower width still shows the whole
        photo (side bars stay black); it is only used when the safe frame is short.
        """
        width = W if not width else int(width)
        x = (W - width) // 2 if x is None else int(x)
        if shot['kind'] != 'collage':
            height = height if height is not None else max(2, round(self.photo_height(shot) * width / W))
            band = ImageOps.fit(shot['photo'][1], (width, height), Image.Resampling.LANCZOS)
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
            natural = self.resize_w(shot['photo'][1], W).height
            if shot.get('label') == '户型':
                return natural
            # Reclaim some of the legacy templates' empty margins without
            # exceeding a 20% crop, including the full camera-motion envelope.
            zoom = 1 + shot.get('kb_strength', 0)
            return max(natural, int(min(1120, natural / (0.80 * zoom**2))))
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
            photo_h = max(2, round(self.photo_height(shot) * photo_w / W))
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
        origin, photo_h, photo_w, photo_x = self._contain_shot(shot, above, tail, prefer_min=SAFE_TOP)
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
        origin, photo_h, photo_w, photo_x = self._contain_shot(shot, 0, y, prefer_min=SAFE)
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
        origin, photo_h, photo_w, photo_x = self._contain_shot(shot, above, tail, prefer_min=SAFE)
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
        origin, photo_h, photo_w, photo_x = self._contain_shot(shot, above, tail, prefer_min=SAFE)
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
        tracking = (4, 2, 3)[self.variant['style']]
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
        style = self.variant['style']
        if style == 1:
            draw.rounded_rectangle(rect, radius=12, outline=GOLD, width=2)
        elif style == 2:
            draw.line((rect[0], rect[3]-3, rect[0]+min(width,140), rect[3]-3), fill=GOLD, width=3)
        else:
            draw.rounded_rectangle(rect, radius=12, fill=GOLD)
        self._note(rect, text, 'tag', size)
        t, _b = self.ink('国8', 'sans', size)
        self.draw(draw, (rect[0] + pad_x, top + PILL_PAD_Y - t), text, 'sans', size,
                  '#0A0704' if style == 0 else GOLD, tracking=2, record=False)

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

    def reference_layers(self, shot):
        """Shared editorial grid: intact photographs, compact type, measured whitespace.

        All coordinates are authored at 1080x1920. A page is one vertically
        balanced group, not independently anchored top and bottom panels.
        """
        key = ('composition-v13', id(shot))
        if key in self.cache and not self._capture:
            return self.cache[key]
        name = self.template_name
        cream = name == 'cream_editorial'
        bg, fg, muted = ('#F4F0E7', '#292824', '#716D64') if cream else ('#121313', '#F1EEE7', '#ADA99F')
        accent = '#A34735' if cream else '#D2B887'
        if name == 'mono_film':
            accent = fg
        elif name == 'vermilion_vertical':
            accent = '#E47765'
        if name == 'editorial':
            accent = '#E5DDD0'
        elif name == 'ledger':
            bg, accent = '#19221F', '#C6D2B5'
        center = name in ('poster', 'mono_film')
        title_kind = 'sans' if name in ('ledger', 'vermilion_vertical', 'immersive_gold') else 'serif'
        left, width, gap = 72, 936, 24
        end = shot['kind'] == 'end'
        floorplan = shot.get('label') == '户型'
        # Only the first photographic page is a cover. Later hero slots become
        # ordinary room pages, avoiding repeated price/name interruptions.
        hero = shot is self.shots[0] and not end and not floorplan
        photos = shot.get('photos') or ([shot['photo']] if shot.get('photo') else [])
        if len(photos) == 1 and photos[0][1].height > photos[0][1].width:
            width = min(width, round((960 if hero else 1100)*photos[0][1].width/photos[0][1].height))
            left = (W-width)//2
        ops = []

        def plan(text, size, kind='sans', max_width=width, max_lines=3):
            text = str(text or '').strip()
            # Keep numeric values and their units together, including m² and 元/㎡.
            tokens = re.findall(r'\d+(?:[.,]\d+)*(?:元/㎡|元/月|万元|万|㎡|m²|室|厅|厨|卫|层|年|户|%)?|.', text)
            while True:
                font = self.font(kind, size)
                lines, line = [], ''
                for token in tokens:
                    if line and font.getlength(line + token) > max_width:
                        lines.append(line)
                        line = ''
                    line += token
                if line:
                    lines.append(line)
                if (len(lines) <= max_lines and all(font.getlength(v) <= max_width for v in lines)) or size <= 36:
                    break
                size -= 2
            # Rebalance Chinese names to avoid a stranded final character.
            if len(lines) == 2 and len(lines[-1]) == 1 and not re.search(r'\d', text):
                split = (len(text) + 1)//2
                lines = [text[:split], text[split:]]
            boxes = [font.getbbox(v) for v in lines]
            heights = [bb[3]-bb[1] for bb in boxes]
            return dict(lines=lines, boxes=boxes, heights=heights, size=size, kind=kind,
                        height=sum(heights)+16*max(0,len(lines)-1))

        def add(p, y, color=fg, x=left, role='caption', centered=center):
            for text, bb, h in zip(p['lines'], p['boxes'], p['heights']):
                w = bb[2]-bb[0]
                xx = left+(width-w)//2 if centered else x
                ops.append((text, xx, y, bb, p['kind'], p['size'], color, role))
                y += h+16
            return y-16 if p['lines'] else y

        title = self.community if hero or end else shot.get('label', '')
        if title == '封面':
            title = _classify_image(photos[0][0])[1] if photos else '房源'
            if title not in TAGS:
                title = '房源'
        title = title or '房源信息'
        heading = plan('户型图' if floorplan else title, 88 if hero or end else 76, title_kind)
        location = '·'.join(p for p in (self.city,self.district,self.bizcircle) if p)
        kicker = plan(location if hero else ('房源资料' if end and self.community else ''), 38)
        facts = [v for v in (shot.get('meta') or []) if v]
        if hero:
            facts = [v for v in (self.layout_short, self.area) if v]
        elif floorplan:
            facts = [self.layout_full] + facts[:2]
        elif shot.get('hero'):
            facts = self._room_facts(title)
        summary = plan(dot_join(facts[:3]), 42, max_lines=2)
        price = plan(self.price if hero or end else '', 92, 'sans', max_lines=2)
        # Price is one typographic lockup, so a unit can never drift to another column.
        unit = plan(self.unit if end else '', 38)
        rows = [(plan(k, 36, max_width=160), plan(v, 44, max_width=736))
                for k, v in self.end_rows()] if end else []
        row_heights = [max(k['height'],v['height'])+40 for k,v in rows]
        cta = plan(self.cta if end else '', 38)
        body_h = heading['height']
        for p in (kicker, price, unit, summary if not end else cta):
            if p['height']:
                body_h += gap+p['height']
        if rows:
            body_h += 48+sum(row_heights)

        # Exact-ratio rows preserve the complete frame and give every tile a
        # shared edge. Three-photo pages have a full-width lead and a smaller pair.
        rects = []
        if photos:
            ratios = [p[1].width/p[1].height for p in photos]
            if len(photos) == 1:
                h = min(1100 if not hero else 960, width/ratios[0])
                w = h*ratios[0]
                rects = [((width-w)/2, 0, w, h)]
            elif len(photos) == 2 and all(r < 1 for r in ratios):
                h = min(1100, (width-gap)/sum(ratios))
                x = (width-(sum(ratios)*h+gap))/2
                for r in ratios:
                    rects.append((x, 0, h*r, h))
                    x += h*r+gap
            else:
                lead_h = width/ratios[0]
                rects = [(0, 0, width, lead_h)]
                tail_h = (width-gap*(len(photos)-2))/sum(ratios[1:])
                x = 0
                for r in ratios[1:]:
                    rects.append((x, lead_h+gap, tail_h*r, tail_h))
                    x += tail_h*r+gap
            natural_h = max(y+h for x,y,w,h in rects)
            max_h = min(1160, 1480-body_h-40)
            scale = min(1, max_h/natural_h)
            rects = [(left+(width-width*scale)/2+x*scale, y*scale, w*scale, h*scale)
                     for x,y,w,h in rects]
            photo_h = natural_h*scale
        else:
            photo_h = 0
        total_h = body_h + (photo_h+40 if photos else 0)
        top = max(176, int((H-total_h)/2)-32)
        base = Image.new('RGB', (W,H), bg)
        overlay = Image.new('RGBA', (W,H))
        draw = ImageDraw.Draw(overlay)
        y = top
        if floorplan:
            y = add(heading, y)+40
        photo_top = y
        photo_rects, kb = [], []
        for photo, (x, yy, w, h) in zip(photos, rects):
            rect = (round(x), round(photo_top+yy), max(1,round(w)), max(1,round(h)))
            x, yy, w, h = rect
            base.paste(photo[1].resize((w,h), Image.Resampling.LANCZOS), (x,yy))
            photo_rects.append(rect)
            if shot.get('kb') and not floorplan:
                kb.append(dict(src=photo[1], rect=rect, move=shot['kb'], strength=min(.03,shot.get('kb_strength',0))))
        if photos:
            y = int(photo_top+photo_h)+40
        text_top = y
        if kicker['height']:
            y = add(kicker, y, muted)+gap
        if not floorplan:
            y = add(heading,y,role='heading')+gap
        if price['height']:
            y = add(price,y,accent,role='amount')+gap
        if unit['height']:
            y = add(unit,y,muted)+gap
        if end:
            y += 24 if rows else 0
            for (label,value), rh in zip(rows,row_heights):
                draw.line((left,y-16,left+width,y-16),fill=muted,width=1)
                add(label,y,muted,centered=False)
                add(value,y,x=left+200,centered=False)
                y += rh
            if cta['height']:
                y = add(cta,y+24,muted)
        elif summary['height']:
            y = add(summary,y,muted)
        for text,x,yy,bb,kind,size,color,role in ops:
            draw.text((x-bb[0],yy-bb[1]),text,font=self.font(kind,size),fill=color)
            self._note((x,yy,x+bb[2]-bb[0],yy+bb[3]-bb[1]),text,role,size)
        rgba = np.asarray(overlay)
        alpha = rgba[...,3:4].astype(np.uint16)
        hit = dict(base=base,base_np=np.asarray(base),tb=(rgba[...,:3].astype(np.uint16)*alpha+127)//255,
                   inv=255-alpha,kb=kb,photo_rects=photo_rects,text_top=text_top,content_bottom=y)
        if not self._capture:
            self.cache[key] = hit
        return hit

    def _v14_cinematic(self, c):
        """01 / demo1: edge-to-edge picture, gold lower caption, dark dossier."""
        if c.end:
            c.text('房源资料',(72,224,936,60),42,color=c.accent,align='center')
            c.name((72,344,936,230),104,kind='serif',align='center')
            c.amount((72,610,936,190),160,align='center')
            c.table((120,920,840,780))
        elif c.plan:
            c.text('户型格局',(72,188,936,70),48,color=c.accent,align='center')
            c.gallery((72,360,936,1060))
            c.text(self.layout_full,(72,1472,936,100),74,align='center')
            c.text(dot_join([v for v in (f'建面{self.area}' if self.area else '',f'套内{self.inner_area}' if self.inner_area else '') if v]),(72,1610,936,110),46,color=c.muted,align='center')
        else:
            c.text(c.location if c.hero else c.room+'实拍',(72,176,936,96),44,color=c.accent)
            c.gallery((0,302,1080,1020),mode='lead')
            if c.hero:
                c.amount((72,1380,936,150),140)
                c.name((72,1548,936,120),88,kind='serif')
                c.summary((72,1704,936,60),44)
            else:
                c.name((72,1400,936,130),112,kind='serif')
                c.summary((72,1570,936,170),48)








    def _v14_cinema_frame(self, c):
        """03 / demo3: title above a wide film window, no fake perforations."""
        if c.end:
            c.name((72,200,936,224),100,kind='serif')
            c.rule(72,484,936,c.fg)
            c.amount((72,546,936,180),168,align='right')
            c.table((72,900,936,800))
        elif c.plan:
            c.name((72,210,936,116),96,align='center',kind='serif')
            c.rule(72,390,936,c.fg)
            c.gallery((48,470,984,960))
            c.rule(72,1490,936,c.fg)
            c.summary((72,1550,936,180),48,align='center')
        else:
            c.text(c.location if c.hero else c.room+'实拍',(72,176,936,94),42,align='center')
            c.name((72,326,936,232),118,kind='serif',align='center')
            c.rule(72,606,936,c.fg)
            c.gallery((0,650,1080,790),mode='columns')
            c.rule(72,1484,936,c.fg)
            if c.hero:c.amount((72,1530,936,128),120,align='center')
            c.summary((72,1690 if c.hero else 1560,936,80 if c.hero else 150),44,align='center')

    def _v14_vertical(self, c):
        """04 / demo4: separate vertical title rail, images left, red price."""
        if c.end:
            c.name((72,210,756,240),94,kind='serif')
            c.amount((72,532,756,166),128)
            c.table((72,850,756,850),columns=2,colored=True)
            for i,char in enumerate('房源资料'):
                c.text(char,(900,240+i*104,108,100),80,color=c.accent,kind='serif')
        elif c.plan:
            c.name((72,190,936,110),84,color=c.accent,kind='serif')
            c.gallery((72,380,936,1140))
            c.summary((72,1590,936,162),50)
        else:
            c.text(c.location if c.hero else c.room+'实拍',(72,176,740,110),42,color=c.accent)
            title=c.title
            if len(title)<=12 and not re.search(r'\d',title):
                sz=72 if len(title)<=6 else 68
                per_column=len(title) if len(title)<=6 else math.ceil(len(title)/2)
                ph=min(1100,730*c.photos[0][1].height/c.photos[0][1].width) if len(c.photos)==1 else 1100
                top=max(320,round((1920-ph-300)/2))
                for i,char in enumerate(title):
                    c.text(char,(930-(i//per_column)*80,top+(i%per_column)*104,78,94),sz,kind='serif')
                c.gallery((72,top,730,ph),mode='lead',align='top')
            else:
                c.name((72,310,936,218),86,kind='serif')
                c.gallery((72,570,936,872),mode='stack')
            edge=max((y+h for x,y,w,h in c.photo_rects),default=1200)
            if c.hero:c.amount((72,edge+54,936,134),122)
            c.summary((72,edge+(220 if c.hero else 54),936,100 if c.hero else 220),46)

    def _v14_price_poster(self, c):
        """05: price first, strong top masthead and photograph below it."""
        if c.end:
            c.text('房源资料',(72,176,936,60),42,color=c.accent)
            c.amount((72,300,936,190),176)
            c.name((72,554,936,212),92)
            c.table((72,870,936,820),colored=True)
        elif c.plan:
            c.text(self.layout_short or '户型图',(72,200,936,160),118,color=c.accent)
            c.text(dot_join([v for v in (f'建面{self.area}' if self.area else '',f'套内{self.inner_area}' if self.inner_area else '') if v]),(72,408,936,110),54)
            c.gallery((48,600,984,1100))
        else:
            c.text(c.location if c.hero else '房间实拍',(72,176,936,84),42)
            if c.hero:
                c.amount((72,310,936,190),174)
                c.name((72,538,936,160),88)
            else:
                c.name((72,310,936,200),150,color=c.accent)
                c.summary((72,548,936,140),50)
            c.gallery((0,740,1080,908),mode='columns')
            if c.hero:c.summary((72,1698,936,70),46)

    def _v14_side_ledger(self, c):
        """06: genuine left/right split, facts in the dark rail, photo right."""
        c.rect((0,0,336,H),'#233F38')
        if c.end:
            c.text('房源资料',(72,200,220,160),62,color='#EFEBDC',lines=2)
            c.name((384,200,624,250),84,kind='serif')
            c.amount((384,530,624,170),120)
            # Full width white sheet bridges the rail below the identity.
            c.rect((48,830,1032,1720),'#F5F2E9')
            c.table((72,860,936,810))
        elif c.plan:
            c.text('户型',(72,210,220,100),70,color='#EFEBDC')
            c.text(self.layout_full,(384,210,624,190),60)
            c.gallery((72,510,936,1030))
            c.text(self.area,(384,1630,624,95),62,color=c.accent)
        else:
            if c.hero:c.name((384,200,624,238),90,kind='serif')
            if c.hero:
                c.amount((384,478,624,150),108)
                for i,fact in enumerate(c.facts[:3]):
                    c.text(fact,(72,744+i*160,220,136),46,color='#F5F2E9')
            else:
                c.text(c.room,(72,420,220,210),70,color='#F5F2E9',role='heading')
                for i,fact in enumerate(c.facts[:3]):
                    c.text(fact,(72,800+i*174,220,150),42,color='#DEDCCD')
            c.gallery((364,680 if c.hero else 420,644,970 if c.hero else 1140),mode='stack',align='top')
            edge=max((y+h for x,y,w,h in c.photo_rects),default=1450)
            c.text(c.location if c.hero else '',(364,min(1660,edge+48),644,112),42,color=c.muted)

    def _v14_dual_panel(self, c):
        """07: two picture acts separated by a title bridge; no duplicated photo."""
        if c.end:
            c.name((72,200,936,230),100,kind='serif')
            c.rect((0,520,W,790),'#7B4438')
            c.text(self.price,(72,592,936,160),142,color='#FFF7EA',role='amount')
            c.table((72,906,936,790),columns=2,colored=True)
        elif c.plan:
            c.text(self.layout_full or '户型图',(72,190,936,150),86,kind='serif')
            c.gallery((72,448,936,1010))
            c.rect((0,1530,W,1800),'#7B4438')
            c.text(dot_join([v for v in (f'建面{self.area}' if self.area else '',f'套内{self.inner_area}' if self.inner_area else '') if v]),(72,1600,936,145),56,color='#FFF7EA')
        elif len(c.photos)>1:
            c.gallery((72,176,936,690),indices=[0])
            c.rule(72,916,936,c.accent)
            c.name((72,960,936,116),98,kind='serif')
            c.summary((72,1100,936,120),44)
            c.gallery((72,1270,936,464),mode='row',indices=range(1,len(c.photos)))
        else:
            c.text(c.location if c.hero else c.room+'实拍',(72,176,936,70),42,color=c.accent)
            c.gallery((72,300,936,820))
            c.rect((0,1180,W,1580),'#7B4438')
            c.name((72,1232,936,180),100,color='#FFF7EA',kind='serif')
            if c.hero:c.text(self.price,(72,1440,936,130),116,color='#FFF7EA',role='amount')
            c.summary((72,1640,936,130),46)

    def _v14_blueprint(self, c):
        """08: technical dossier, white image plate and three-column metrics."""
        if c.end:
            c.name((72,190,936,210),94)
            c.amount((72,460,936,156),142)
            c.rect((48,700,1032,1710),'#F1F4F1')
            c.fg,c.muted,c.accent='#192E3A','#52616A','#23607A'
            c.table((72,760,936,840))
        elif c.plan:
            c.name((72,190,650,110),90)
            c.text(self.area,(760,200,248,110),58,color=c.accent)
            c.text(self.layout_full,(72,340,936,112),62)
            c.rect((48,524,1032,1540),'#FFFFFF')
            c.gallery((72,548,936,968))
            c.summary((72,1610,936,144),46)
        else:
            c.name((72,182,650,230),90)
            c.text(self.area if c.hero else f'{len(c.photos)}张实拍',(780,202,228,166),48,color=c.accent)
            if c.hero:c.amount((72,438,936,140),124)
            c.rule(72,624,936)
            c.rect((48,678,1032,1440),'#FFFFFF')
            c.gallery((72,702,936,714),mode='columns')
            facts=c.facts[:3]
            for i,fact in enumerate(facts):
                x=72+i*320
                c.rule(x,1530,296,c.accent)
                c.text(fact,(x,1580,296,174),50)

    def distinct_layers(self, shot):
        key=('composition-v14',id(shot))
        if key in self.cache and not self._capture:return self.cache[key]
        palettes={
            'tour_route': ('#F7F1E7','#243D31','#50795A','#667265'),
            'cinema_immersive': ('#101512','#FFFDF6','#E8CE91','#D6D6CA'),
            'ad_photo_story_v20': ('#F8F3E9','#28362E','#B3412D','#565E54'),
            'v14_cinematic': ('#101111','#F6F1E7','#E7C887','#C1B9AA'),
            'ad_masthead': ('#192E2B','#FCF6E9','#F1CC78','#D3DCD4'),
            'ad_photo_story': ('#F8F3E9','#28362E','#B3412D','#565E54'),
            'v14_editorial': ('#F4EFE4','#242721','#B2372A','#50544B'),
            'v14_cinema_frame': ('#111111','#F5F5F0','#FFFFFF','#BFC0BB'),
            'v14_vertical': ('#F0E9DB','#29251F','#AF3D2C','#6F695E'),
            'v14_price_poster': ('#222421','#FAF7E9','#EEE36C','#CAC7B7'),
            'v14_side_ledger': ('#F5F2E9','#24372F','#7B4D22','#687268'),
            'v14_dual_panel': ('#ECE5D9','#322B27','#7B4438','#72665D'),
            'v14_blueprint': ('#152B3A','#F5F7F3','#9BD6E1','#A2B9C0'),
        }
        c=TemplateCanvas(self,shot,*palettes[self.template_name])
        if self.template_name in AD_TEMPLATES and c.plan:
            c.fg, c.muted = '#28362E', '#565E54'
        drawer = slideshow_templates.DRAWERS.get(self.template_name)
        if drawer:
            drawer(self, c)
        else:
            getattr(self, '_' + self.template_name)(c)
        if c.end and self.cta and self.template_name not in NARRATIVE_TEMPLATES:
            c.text(self.cta,(72,1724,936,52),38,color=c.muted,lines=1)
        hit=c.finish()
        if not self._capture:self.cache[key]=hit
        return hit

    def layers(self, shot):
        if self.template_name in V14_TEMPLATES + AD_TEMPLATES + NARRATIVE_TEMPLATES:
            return self.distinct_layers(shot)
        return self.reference_layers(shot)

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
        return self.compose(self.shots[-1], None)

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
                first_box = len(self.text_boxes)
                layer = self.layers(shot)
                boxes = self.text_boxes[first_box:]
                animation = shot['text_animation']
                if animation['effect'] == 'grouped':
                    for box in boxes:
                        event = next((v for v in layer.get('text_events', [])
                                      if v['rect'][0] <= box['left'] and v['rect'][1] <= box['top']
                                      and v['rect'][2] >= box['right'] and v['rect'][3] >= box['bottom']), None)
                        if event and event['effect'] == 'rise':
                            self.text_boxes.append(dict(box, top=box['top']+event['offset'],
                                                        bottom=box['bottom']+event['offset']))
                if animation['effect'] == 'rise' and boxes:
                    bottom = 1776
                    animation['offset'] = min(animation['offset'], max(0, bottom-max(b['bottom'] for b in boxes)))
                    for box in boxes:
                        moved = dict(box, top=box['top']+animation['offset'], bottom=box['bottom']+animation['offset'])
                        self.text_boxes.append(moved)
        finally:
            self._capture = False
        violations = []
        for box in self.text_boxes:
            l, t, r, b = box['left'], box['top'], box['right'], box['bottom']
            reasons = []
            if l < 0 or t < 0 or r > W or b > H:
                reasons.append('canvas')
            safe_box = (72,32,1008,1888) if self.template_name in NARRATIVE_TEMPLATES else (72,144,1008,1776)
            if l < safe_box[0] or t < safe_box[1] or r > safe_box[2] or b > safe_box[3]:
                reasons.append('safe')
            minimum = 36 if box['role'] in ('heading', 'amount', 'caption') else (MIN_TITLE if box['role'] in ('title', 'price') else MIN_TEXT)
            if box['size'] < minimum:
                reasons.append('min-size')
            if reasons:
                item = dict(box)
                item['violation'] = '+'.join(reasons)
                violations.append(item)
        status = 'PASS' if not violations else 'FAIL'
        return {'status': status, 'count': len(self.text_boxes), 'safe': SAFE,
                'violations': violations}
