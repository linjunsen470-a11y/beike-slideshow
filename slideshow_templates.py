"""The five recommended video styles. Pure drawing functions using the shared renderer.

The old v14_editorial alias shares the editorial drawing function.
"""
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from PIL import ImageOps
from pathlib import Path
import math
import numpy as np
import re
from slideshow_common import (
    AD_TEMPLATES, FONT_DIR, H, W, dot_join,
    installed_font, sc_index,
)

def _v14_editorial(self, c):
    """02 / mobile review: large photo fields and a compact shared caption.

    Related landscape pairs span the phone; single views retain room context.
    This template alone owns these picture allocations and typography rules.
    """
    regular_path = installed_font(FONT_DIR / 'NotoSansCJKsc-Regular.otf',
                                  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                                  'msyh.ttc')
    self.editorial_body_path = regular_path if Path(regular_path).is_file() else self.sans_path

    def face(kind, size):
        # Strong sans headings and readable bold facts; small labels stay quiet.
        if kind == 'serif' or (kind == 'regular' and size >= 44):
            return self.font('sansBold', size)
        if kind != 'regular' or not Path(regular_path).is_file():
            return self.font(kind, size)
        key = ('editorial-regular', size)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(regular_path, size, index=sc_index(regular_path))
        return self.fonts[key]

    def block(value, width, size=44, kind='regular', color=None, role='caption', lines=2):
        value = str(value or '').strip()
        if not value:
            return None
        token_pattern = r'\d+(?:[.,]\d+)*(?:元/㎡|元/月|万元|万|㎡|m²|室|厅|厨|卫|层|年|户|%)?'
        if role == 'heading':
            token_pattern += r'|[东西南北中]区|[一二三四五六七八九十]+期|花园|公寓|住宅|别墅|小区'
        tokens = re.findall(token_pattern + r'|.', value)
        for sz in range(size, 35, -2):
            font = face(kind, sz)
            rows, row = [], ''
            for token in tokens:
                if row and font.getlength(row + token) > width - 4 and token not in '，。·、）':
                    rows.append(row)
                    row = ''
                row += token
            if row:
                rows.append(row)
            if len(rows) == 2 and len(rows[-1]) <= 2 and not re.search(r'\d', value):
                candidates = [[ ''.join(tokens[:i]), ''.join(tokens[i:])]
                              for i in range(1, len(tokens))]
                candidates = [pair for pair in candidates
                              if all(font.getlength(v) <= width - 4 for v in pair)]
                if candidates:
                    rows = min(candidates, key=lambda pair: abs(font.getlength(pair[0]) - font.getlength(pair[1])))
            bounds = [font.getbbox(v) for v in rows]
            if len(rows) <= lines and all(bb[2] - bb[0] <= width for bb in bounds):
                return dict(rows=rows, bounds=bounds, font=font, size=sz, role=role,
                            color=color or c.fg, width=width,
                            height=sum(bb[3] - bb[1] for bb in bounds) + 14 * (len(rows) - 1))
        raise ValueError(f'v14_editorial: text does not fit {value!r} in {width}px')

    def paint(item, x, y):
        if not item:
            return y
        for text, bb in zip(item['rows'], item['bounds']):
            xx = x + (item['width'] - (bb[2] - bb[0])) / 2 if (not c.end or item['role'] in ('heading', 'amount')) else x
            c.draw.text((round(xx - bb[0]), round(y - bb[1])), text,
                        font=item['font'], fill=item['color'])
            rect = (round(xx), round(y), round(xx + bb[2] - bb[0]), round(y + bb[3] - bb[1]))
            self._note(rect, text, item['role'], item['size'])
            c.boxes.append(dict(text=text, rect=rect, role=item['role']))
            y += bb[3] - bb[1] + 14
        return y - 14

    def height(items, gap=16):
        return sum(v['height'] for v in items) + gap * max(0, len(items) - 1)

    def paint_items(items, x, y, gap=16):
        for i, item in enumerate(items):
            y = paint(item, x, y) + (gap if i + 1 < len(items) else 0)
        return y

    def identity(width=936):
        return [v for v in (block(c.title, width, 82, 'serif', role='heading'),
                            block(c.price, width, 112, 'sansBold', c.accent, 'amount')) if v]

    # No zoom on 02. Its single-landscape sweep below is a lateral move;
    # paired views and plans remain static. Other templates keep their motion.
    c.shot = dict(c.shot, kb_strength=0.0)

    if c.plan:
        # Remove only outside white paper, retaining all ink, dimensions and
        # compass marks plus a safety border. Never crop the diagram to fill.
        trimmed = []
        for name, src in c.photos:
            pixels = np.asarray(src.convert('RGB'))
            yy, xx = np.where(np.min(pixels, axis=2) < 248)
            if len(xx):
                border = max(16, round(min(src.size) * .012))
                bounds = (max(0, int(xx.min()) - border), max(0, int(yy.min()) - border),
                          min(src.width, int(xx.max()) + border + 1),
                          min(src.height, int(yy.max()) + border + 1))
                src = src.crop(bounds)
            trimmed.append((name, src))
        c.photos = trimmed
        c.rect((0, 0, W, H), '#FFFFFF')
        paint(block('户型图', 936, 80, 'serif', role='heading'), 72, 144)
        paint(block(self.layout_full, 936, 62, 'sansBold'), 72, 250)
        c.gallery((36, 390, 1008, 1090))
        values = [(k, v) for k, v in [('建筑面积', self.area), ('套内面积', self.inner_area)] if v]
        for i, (label, value) in enumerate(values):
            x = 72 + i * 488
            paint(block(label, 448, 38, color=c.muted), x, 1550)
            paint(block(value, 448, 84, 'sansBold'), x, 1624)
        return

    if c.end:
        # An unused real photograph anchors the closing information sheet.
        # With no spare photo the fact sheet remains readable on its own.
        header = identity()
        if not c.photos:
            # A text-only closing sheet needs a full-width reading grid,
            # not a small two-column block stranded at the top.
            rows = self.end_rows()
            y = paint_items(header, 72, 180) + 72
            row_h = min(186, (1744 - y) / max(1, len(rows)))
            for label, value in rows:
                c.rule(72, y - 20, 936, '#D9D4C9')
                paint(block(label, 164, 40, color=c.muted), 72, y + 8)
                paint(block(value, 724, 60), 284, y)
                y += row_h
            return
        cells = [(block(label, 448, 36, color=c.muted), block(value, 448, 46))
                 for label, value in self.end_rows()]
        row_heights = [max(a['height'] + 16 + v['height'] for a, v in cells[i:i+2])
                       for i in range(0, len(cells), 2)]
        table_h = sum(row_heights) + 30 * max(0, len(row_heights) - 1)
        top = 144
        if c.photos:
            photo_h = min(936, 1744 - 48 - height(header) - 48 - table_h)
            c.picture(0, (0, 0, W, photo_h), crop=True, align='top')
            top = photo_h + 48
        y = paint_items(header, 72, top)
        y += 48
        for row, rh in enumerate(row_heights):
            for col, (label, value) in enumerate(cells[row*2:row*2+2]):
                x = 72 + col * 488
                value_y = paint(label, x, y) + 16
                paint(value, x, value_y)
            y += rh + 30
        return

    ratios = [p[1].width / p[1].height for p in c.photos]
    if len(ratios) == 2 and all(r >= 1.1 for r in ratios):
        # Two related full-width views joined by one compact caption band.
        # No outer mat, tiny third tile, artificial backdrop or repeated data.
        items = identity() if c.hero else [block(c.title, 936, 80, 'serif', role='heading')]
        items += [block(dot_join(c.facts[:3] if c.hero else c.facts[:2]),
                        936, 44 if c.hero else 48, color=c.muted)]
        if c.hero:
            items += [block(c.location, 936, 36, color=c.muted)]
        items = [v for v in items if v]
        if self.template_name in AD_TEMPLATES:
            # Two distinct ad hierarchies: masthead first, or photo story first.
            band = height(items) + 192
            photo_h = (H - band - 12) / 2
            if self.template_name == 'ad_masthead':
                paint_items(items, 72, 144)
                c.picture(0, (0, band, W, photo_h), crop=True)
                c.picture(1, (0, band + photo_h + 12, W, photo_h), crop=True)
            else:
                c.picture(0, (0, 0, W, photo_h), crop=True)
                c.picture(1, (0, photo_h + 12, W, photo_h), crop=True)
                paint_items(items, 72, H - band + 32)
            return
        caption_h = height(items) + 48
        available = H - caption_h
        # Allocate in proportion to natural height; the original aspect
        # ratios remain equally important even with differently wide photos.
        natural = [W / r for r in ratios]
        first_h = available * natural[0] / sum(natural)
        second_h = available - first_h
        c.picture(0, (0, 0, W, first_h), crop=True, align='bottom')
        paint_items(items, 72, first_h + 24)
        c.picture(1, (0, first_h + caption_h, W, second_h), crop=True, align='top')
        return

    if len(ratios) >= 2:
        # Portrait/mixed pairs share a large top-aligned picture field.
        items = identity() if c.hero else [block(c.title, 936, 80, 'serif', role='heading')]
        items += [block(dot_join(c.facts[:2]), 936, 48, color=c.muted)]
        items = [v for v in items if v]
        available = min(1480, 1680 - height(items) - 48)
        c.gallery((36, 120, 1008, available), mode='row', align='top')
        edge = max((y+h for x,y,w,h in c.photo_rects), default=120)
        paint_items(items, 72, edge + 48)
        return

    if ratios and ratios[0] >= 1.1 and self.kenburns:
        # Phone-sized single landscape: reveal the whole source over time,
        # holding both endpoints. At least 55% stays visible in every frame
        # (the endpoints overlap); there is no zoom, blur or repeated tile.
        items = identity() if c.hero else [block(c.title, 936, 80, 'serif', role='heading')]
        items += [block(dot_join(c.facts[:3] if c.hero else c.facts[:2]),
                        936, 46, color=c.muted)]
        if c.hero:
            items += [block(c.location, 936, 38, color=c.muted)]
        items = [v for v in items if v]
        photo_h = int(min(H - 144 - 96 - height(items), W / ratios[0] / .55))
        rect = (0, 0, W, photo_h)
        src = c.photos[0][1]
        c.base.paste(ImageOps.fit(src, (W, photo_h), Image.Resampling.LANCZOS), (0, 0))
        c.photo_rects.append(rect)
        c.kb.append(dict(src=src, rect=rect, move='full_pan', strength=0.0,
                         framing='full-pan'))
        paint_items(items, 72, photo_h + 48)
        return

    # A single landscape gets the largest modest crop that preserves at
    # least 83% of the source. Portraits use almost the whole phone height.
    # This is one photograph, never a duplicated crop used as filler.
    items = identity() if c.hero else [block(c.title, 936, 96, 'serif', role='heading')]
    facts = c.facts[:3] if c.hero else c.facts[:2]
    if c.hero:
        items += [block(dot_join(facts), 936, 50, color=c.muted),
                  block(c.location, 936, 38, color=c.muted)]
    else:
        items += [block(value, 936, 64, color=c.muted) for value in facts]
    items = [v for v in items if v]
    photo_h = min(1480, W / ratios[0] / .83, 1600 - height(items) - 48) if ratios else 0
    total = photo_h + (48 if photo_h else 0) + height(items)
    y = max(144, (H - total) / 2 - 16)
    if ratios:
        c.picture(0, (0, y, W, photo_h), crop=True)
    paint_items(items, 72, y + photo_h + (48 if photo_h else 0))


def _ad_photo_story_v20(self, c):
    """Revision 23: small outer margins; photos fill remaining canvas height."""
    c.shot = dict(c.shot, kb=None, kb_strength=0.0)
    c.text_events = []

    def text(value, box, size=52, color=None, align='center', role='caption',
             lines=2, delay=0.0, effect='rise', duration=.36):
        first = len(c.boxes)
        bottom = c.text(value, box, size, color=color, kind='sansBold',
                        align=align, role=role, lines=lines)
        boxes = c.boxes[first:]
        if boxes:
            rect = (min(b['rect'][0] for b in boxes), min(b['rect'][1] for b in boxes),
                    max(b['rect'][2] for b in boxes), max(b['rect'][3] for b in boxes))
            # All travel stays in the text band, never over the next photograph.
            offset = min(28, max(0, box[1] + box[3] - rect[3]), max(0, 1888 - rect[3]))
            c.text_events.append(dict(rect=rect, delay=delay, duration=duration,
                                     effect=effect, offset=offset,
                                     initial_alpha=.55 if effect == 'pop' else 0.0))
        return bottom

    def photo(index, y, height, sweep=False):
        if index >= len(c.photos):
            return
        src = c.photos[index][1]
        ratio = src.width / src.height
        if sweep and self.kenburns and ratio >= 1.1 and ratio > W / height:
            # The user prefers edge-filled images over the old 55% window
            # cap. Preserve geometry/full height and reveal both sides.
            rect = (0, int(y), W, int(height))
            c.base.paste(ImageOps.fit(src, (W, int(height)), Image.Resampling.LANCZOS), rect[:2])
            c.photo_rects.append(rect)
            c.kb.append(dict(src=src, rect=rect, move='full_pan', strength=0.0, framing='full-pan'))
        else:
            c.picture(index, (0, y, W, height), crop=True, align='top')

    if c.plan:
        # Reuse the full-plan crop protection, then animate only its text.
        _v14_editorial(self, c)
        for i, item in enumerate(c.boxes):
            l, t, r, bottom = item['rect']
            delay = 0.0 if t < 230 else .20 if t < 390 else .44 if l < 540 else .64
            c.text_events.append(dict(rect=(l,t,r,bottom), delay=delay, duration=.36,
                                     effect='rise', offset=min(24,1776-bottom), initial_alpha=0.0))
        return
    if c.end:
        if c.photos:
            long_name = self.font('sansBold',62).getlength(self.community) > 932
            top = 1264 - (70 if long_name else 0) - (150 if self.cta else 0)
            photo(0, 0, top-24, sweep=True)
        else:
            top = 240
        y = text(self.price or '房源资料', (72, top, 936, 136), 128,
                 c.accent, role='amount', effect='pop') + 12
        y = text(self.community, (72, y, 936, 128), 62,
                 role='heading', delay=.18) + 20
        cards = self._story_cards()
        # Compact rows follow measured type, instead of fixed empty spacers.
        row_h = 196 if c.photos else 240
        for i, (label, value) in enumerate(cards):
            x, yy = 72 + (i % 2) * 488, y + (i // 2) * (row_h + 12)
            c.rect((x, yy, x + 448, yy + row_h), '#E8DFCE')
            delay = .34 + i * .16
            if label == '楼层':
                # The value already says “低楼层”; a second “楼层” label adds noise.
                text(value, (x+24, yy+66, 400, 96), 56, lines=1, delay=delay+.06)
            else:
                text(label, (x+24, yy+18, 400, 54), 42, c.muted, delay=delay)
                text(value, (x+24, yy+80, 400, row_h-94),
                     60 if label == '单价' else 72, lines=1 if label == '单价' else 2,
                     delay=delay+.06)
        if not cards:
            y = text(dot_join([self.layout_short,self.area]) or '房源资料待补充',
                     (72,y,936,120),60,delay=.34)
        else:
            y += math.ceil(len(cards)/2) * (row_h+12)
        if self.cta:
            text(self.cta, (72,min(y+20,1632),936,144),46,delay=1.0,lines=2)
        elif not c.photos and c.location:
            text(c.location,(72,min(y+32,1640),936,120),44,c.muted,delay=.98)
        return
    if c.hero:
        # A small measured masthead releases the entire lower canvas to the
        # photograph. There is no empty paper tail under a short name.
        y = text(self.price or self.layout_short or '房源实拍',
                 (72,32,936,164),156,c.accent,role='amount',effect='pop') + 12
        facts = dot_join([self.layout_short if self.price else '', self.area])
        if facts:
            y = text(facts,(72,y,936,92),58,delay=.28) + 12
        y = text(self.community or '房源信息',(72,y,936,144),64,
                 role='heading',delay=.56) + 20
        photo(0, y, H-y, sweep=True)
        return
    if len(c.photos) == 2:
        photo(0, 0, 880)
        text(c.room+'实拍',(72,916,936,108),84,role='heading',delay=.12)
        photo(1,1040,880)
        return
    if c.photos:
        title = c.room if c.shot['slot']=='community' else c.room+'实拍'
        def ink_height(value, size):
            bounds = self.font('sansBold',size).getbbox(value)
            return bounds[3]-bounds[1]
        facts = c.facts[:2]
        caption_h = 24 + ink_height(title,80) + 12 + sum(ink_height(f,46)+8 for f in facts) + 32
        height = H-caption_h
        photo(0,0,height,sweep=True)
        y = height+24
        y = text(title,(72,y,936,112),80,role='heading',delay=.10) + 12
        for i,fact in enumerate(facts):
            y = text(fact,(72,y,936,68),46,c.muted,delay=.40+i*.22) + 8


def _reference_text(self, c, value, box, size=56, delay=0.0, color=None,
                    align='left', effect='rise', lines=2):
    first=len(c.boxes)
    bottom=c.text(value,box,size,color=color,kind='sansBold',align=align,lines=lines)
    boxes=c.boxes[first:]
    if boxes:
        rect=(min(b['rect'][0] for b in boxes),min(b['rect'][1] for b in boxes),
              max(b['rect'][2] for b in boxes),max(b['rect'][3] for b in boxes))
        c.text_events.append(dict(rect=rect,delay=delay,duration=.38,effect=effect,
            offset=min(26,max(0,1888-rect[3]),max(0,box[1]+box[3]-rect[3])),
            initial_alpha=.6 if effect=='pop' else 0.0))
    return bottom


def _reference_photo(self, c, box, radius=0):
    if not c.photos:return
    x,y,w,h=map(int,box)
    src=c.photos[0][1]
    fitted=ImageOps.fit(src,(w,h),Image.Resampling.LANCZOS)
    mask=None
    if radius:
        mask=Image.new('L',(w,h))
        ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1),radius,fill=255)
    c.base.paste(fitted,(x,y),mask)
    c.photo_rects.append((x,y,w,h))
    if self.kenburns and src.width/src.height>w/h:
        c.kb.append(dict(src=src,rect=(x,y,w,h),move='full_pan',strength=0.0,
                         framing='full-pan',mask=mask))


def _reference_plan(self,c,box):
    # Keep every inked dimension, label and compass mark, with an outer border.
    photos=[]
    for name,src in c.photos:
        yy,xx=np.where(np.min(np.asarray(src.convert('RGB')),axis=2)<248)
        if len(xx):
            border=max(16,round(min(src.size)*.012))
            src=src.crop((max(0,int(xx.min())-border),max(0,int(yy.min())-border),
                          min(src.width,int(xx.max())+border+1),min(src.height,int(yy.max())+border+1)))
        photos.append((name,src))
    c.photos=photos
    c.gallery(box)


def _tour_route(self,c):
    """demo-A: a visible route, warm paper and large rounded photographs."""
    c.text_events=[]
    index=next(i for i,s in enumerate(self.shots) if s is c.shot)
    total=len(self.shots)
    tx=lambda value,box,size=56,delay=0.0,**kw:_reference_text(self, c,value,box,size,delay,**kw)
    tx('看房路线',(72,32,600,66),42,color=c.accent)
    tx(f'{index+1:02d} / {total:02d}',(744,32,264,66),42,align='right',color=c.muted)
    route=ImageDraw.Draw(c.base)
    route.line((88,126,992,126),fill='#D9DECF',width=5)
    if total>1:
        route.line((88,126,88+904*index/(total-1),126),fill=c.accent,width=5)
    for i in range(total):
        xx=88+904*i/max(1,total-1)
        route.ellipse((xx-10,116,xx+10,136),fill=c.accent if i<=index else '#D9DECF')
    if c.plan:
        tx('走完路线，再看户型',(72,176,936,124),82,delay=.14)
        _reference_plan(self, c,(24,340,1032,1120))
        tx(self.layout_full,(72,1494,936,124),72,delay=.34,align='center')
        facts=dot_join([f'建筑面积 {self.area}' if self.area else '',
                       f'套内 {self.inner_area}' if self.inner_area else ''])
        tx(facts,(72,1642,936,108),46,delay=.56,align='center',color=c.muted)
        tx(self.cta or dot_join([self.community,self.price]),(72,1798,936,90),48,
           delay=.80,align='center',color=c.accent)
        return
    if c.end:
        tx(self.community or '房源资料',(72,240,936,200),92)
        tx(self.price,(72,500,936,200),156,.20,color=c.accent,effect='pop')
        for i,(label,value) in enumerate(self._story_cards()):
            tx(dot_join([label if label!='楼层' else '',value]),
               (72,820+i*180,936,140),62,.36+i*.14)
        if self.cta:tx(self.cta,(72,1740,936,140),48,.9)
        return
    if c.hero:
        headline=f'走进{self.area}的家' if self.area else '跟着镜头，看看这套房'
        tx(headline,(72,174,936,124),92,.12)
        tx(self.community,(72,300,936,100),54,.36,color=c.muted)
        top=414
    else:
        tx(f'{index+1:02d}  {c.room}实拍' if c.room!='小区' else f'{index+1:02d}  小区环境',
           (72,174,936,124),88,.12)
        top=320
    _reference_photo(self, c,(24,top,1032,1720-top),radius=26)
    next_label=self.shots[index+1]['label'] if index+1<total else ''
    direction='下一视角' if next_label==c.room else '下一站'
    tx(f'{direction} · {next_label}' if next_label else '实景看房',
       (72,1750,936,64),48,.58,color=c.accent)
    tx(dot_join([self.price,self.layout_short,self.area]),(72,1828,936,60),44,.78,color=c.muted)


def _cinema_immersive(self,c):
    """demo-B: edge-filled views, local contrast and restrained gold/white type."""
    c.text_events=[]
    tx=lambda value,box,size=56,delay=0.0,**kw:_reference_text(self, c,value,box,size,delay,**kw)
    index=next(i for i,s in enumerate(self.shots) if s is c.shot)
    if c.plan:
        tx('户型全览',(72,44,936,90),60,color=c.accent)
        _reference_plan(self, c,(24,200,1032,1130))
        tx(self.price,(72,1380,936,166),150,.22,color=c.accent,effect='pop')
        tx(self.layout_full,(72,1572,936,112),70,.42)
        tx(dot_join([self.area,self.community]),(72,1710,936,108),50,.64,color=c.muted)
        if self.cta:tx(self.cta,(72,1820,936,68),42,.88)
        return
    if c.end:
        tx(self.community or '房源资料',(72,220,936,220),98)
        tx(self.price,(72,510,936,190),170,.22,color=c.accent,effect='pop')
        for i,(label,value) in enumerate(self._story_cards()):
            tx(dot_join([label if label!='楼层' else '',value]),
               (72,820+i*180,936,140),64,.36+i*.14)
        if self.cta:tx(self.cta,(72,1740,936,140),48,.9,color=c.accent)
        return
    _reference_photo(self, c,(0,0,W,H))
    # A fixed gradient sits above the moving image, below independent text.
    # The central room stays bright; only the type bands need heavy contrast.
    overlay=np.zeros((H,W,4),dtype=np.uint8)
    alpha=np.interp(np.arange(H),[0,300,1000,1320,1680,1919],[85,0,0,65,175,205])
    overlay[:,:,3]=alpha[:,None].astype(np.uint8)
    c.fixed_overlay=Image.fromarray(overlay,'RGBA')
    decor=ImageDraw.Draw(c.fixed_overlay)
    decor.line((72,1304,220,1304),fill=c.accent,width=5)
    tx('实景看房' if c.hero else dot_join([self.city,self.district]),
       (72,44,936,74),40,color=c.accent)
    if c.hero:
        tx(self.price or '走进这套房',(72,1360,936,190),174,.08,effect='pop')
        tx(dot_join([self.layout_short,self.area]),(72,1580,936,100),62,.38)
        tx(self.community,(72,1730,936,140),66,.64,color=c.accent)
    elif c.room=='小区':
        tx(self.community or '小区实景',(72,1390,936,210),98,.16)
        year=self.year if not self.year or self.year.endswith('年') else self.year+'年'
        tx(dot_join([year+'建成' if year else '', '绿化率'+self.green if self.green else '']),
           (72,1660,936,100),54,.46,color=c.accent)
        tx('小区实景',(72,1802,936,80),42,.70,color=c.muted)
    else:
        tx(f'{index+1:02d}  {c.room}',(72,1460,936,160),116,.16)
        tx('房源实拍',(72,1664,936,90),54,.44,color=c.accent)
        tx(dot_join([self.layout_short,self.area]),(72,1802,936,80),44,.70,color=c.muted)


DRAWERS = {
    'v14_editorial': _v14_editorial,
    'ad_masthead': _v14_editorial,
    'ad_photo_story': _v14_editorial,
    'ad_photo_story_v20': _ad_photo_story_v20,
    'tour_route': _tour_route,
    'cinema_immersive': _cinema_immersive,
}
