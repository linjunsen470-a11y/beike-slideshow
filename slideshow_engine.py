"""Photo sequencing, music timing, camera motion and frame composition."""
from slideshow_layouts import LayoutRenderer
import sfx_tools
from PIL import Image
import hashlib
import math
import numpy as np
import random
import re
from slideshow_common import (
    BLACK, DEMO_AB_TEMPLATES, DISSOLVE_KINDS, DUR_COLLAGE, DUR_COMMUNITY,
    DUR_COVER, DUR_END, DUR_FLOORPLAN, DUR_ROOM, H,
    KB_MOVES, M, MOBILE_LAYOUTS, MOBILE_TEMPLATES, NARRATIVE_TEMPLATES,
    SANS_BLACK_PATH, SANS_BOLD_PATH, SERIF_BLACK_PATH, SERIF_PATH, SHOT_ORDER,
    STORY_TEMPLATE, TAGS, TEMPLATES, TEMPLATE_ORDER, TRANSITIONS,
    TRANSITION_FLOOR, TRANSITION_SECONDS, W, _box_blur, _ease,
    _f32, _shift_edge, _spin_frame, _u8, _whip_slide,
    _zoom_blur, canonical_transition, derived_seed, dot_join, has_tag,
    resolve_listing_type, sc_index, stable_seed,
)

class Magazine(LayoutRenderer):
    def __init__(self, listing, groups, serif_path, cta='', kenburns=True, kb_strength=0.08,
                 transitions='random', transition_dur=0.40, listing_type='auto', seed=None,
                 beat_pulse=False, fps=30, template='gold_classic', variation='subtle',
                 font_profile=None):
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
        self.variation = variation
        self.transition_pool = tuple(TEMPLATES[template]['transitions'])
        if variation == 'subtle' and transitions in ('random', 'rand') and template not in MOBILE_LAYOUTS:
            self.transition_pool = tuple(t for t in self.transition_pool
                                         if t in ('push', 'wipe', 'zoom', 'slide_left', 'light_leak'))
            if len(self.transition_pool) < 3:
                self.transition_pool = ('push', 'wipe', 'zoom', 'light_leak')
        if font_profile:
            self.serif_path = str(font_profile['title_path'])
            self.sans_bold_path = str(font_profile['body_path'])
            self.sans_path = str(font_profile['body_path'])
            self.font_profile_name = font_profile.get('name', '抽卡方案')
        else:
            if str(serif_path) == SERIF_PATH and SERIF_BLACK_PATH.is_file():
                serif_path = str(SERIF_BLACK_PATH)
            self.serif_path = str(serif_path)
            self.sans_path = str(SANS_BLACK_PATH) if SANS_BLACK_PATH.is_file() else SANS_BOLD_PATH
            self.sans_bold_path = SANS_BOLD_PATH
            self.font_profile_name = '默认'
        self.serif_index = sc_index(self.serif_path)
        self.sans_index = sc_index(self.sans_path)
        self.sans_bold_index = sc_index(self.sans_bold_path)
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
        self.variant = {'version': 1, 'mode': variation,
                        'style': random.Random(derived_seed(self.seed, 'layout')).randrange(3)
                        if variation == 'subtle' else 0}
        if self.template_name == STORY_TEMPLATE:
            self.variant['story_revision'] = 23
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
        animation_rng = random.Random(derived_seed(self.seed, 'text'))
        effects = animation_rng.sample(['fade', 'rise', 'reveal'], 2)
        for i, shot in enumerate(self.shots):
            shot['text_animation'] = dict(effect=animation_rng.choice(effects)
                if variation == 'subtle' and template not in NARRATIVE_TEMPLATES and i and shot['dur'] >= 1.5 and shot['kind'] != 'end' else 'none',
                duration=round(animation_rng.uniform(0.18, 0.28), 3),
                offset=animation_rng.randint(12, 24))
            if template in NARRATIVE_TEMPLATES and variation == 'subtle':
                shot['text_animation'] = dict(effect='grouped', duration=1.30, offset=28)
            if variation == 'subtle' and not shot.get('hero'):
                phrases = {'卧室空间': ['卧室空间', '卧室一览', '卧室实拍'],
                           '小区环境': ['小区环境', '小区一览', '小区实景'],
                           '客厅实拍': ['客厅实拍', '客厅空间', '客厅一览']}
                if shot.get('tag') in phrases:
                    shot['tag'] = phrases[shot['tag']][self.variant['style']]
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
        if self.template_name in DEMO_AB_TEMPLATES:
            return self._tour_timeline()
        if self.template_name == STORY_TEMPLATE:
            return self._story_timeline()
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
        if self.template_name in MOBILE_TEMPLATES:
            self._editorial_mobile_photos(shots)
            sections = []
            elapsed = 0.0
            for shot in shots:
                if not sections or sections[-1]['template'] != shot['slot']:
                    sections.append(dict(template=shot['slot'], start=elapsed, duration=0.0))
                sections[-1]['duration'] += shot['dur']
                elapsed += shot['dur']
        seen = []
        for shot in shots:
            for name in shot.get('files') or []:
                if name in seen:
                    raise RuntimeError(f'duplicate photo across shots: {name}')
                seen.append(name)
        return shots, sections

    def shot_order(self):
        if self.template_name in DEMO_AB_TEMPLATES:
            middle = ['living', 'kitchen_bath', 'bedrooms']
            return (['cover'] + (['community'] + middle if self.template_name == 'cinema_immersive'
                                else middle + ['community']) + ['floorplan', 'end'])
        if self.template_name == STORY_TEMPLATE:
            return ['cover', 'floorplan', 'living', 'kitchen_bath', 'bedrooms', 'community', 'end']
        return SHOT_ORDER[self.listing_type]

    def _tour_timeline(self):
        """One photo per stop; a complete plan closes the actual available route."""
        shots = []
        def add(photo, label, slot, duration=2.8, minimum=2.4):
            shot = self._timed(dict(kind='band', label=label, title=label,
                slot=slot, plate=f'tour_{len(shots)}', photos=[photo] if photo else [],
                hero=slot=='cover', meta=[]), (duration,minimum,duration+1))
            shot['read_min'] = minimum
            shots.append(shot)
        pool = [p for key in ('客厅','卧室','阳台','厨房','卫生间','其他')
                for p in self.groups.get(key,[])]
        cover = self._claim_one(pool or self.groups.get('community'), 'tour opening')
        if cover:
            room = next((k for k,ps in self.groups.items() if cover in ps and k!='floorplan'), '房源')
            add(cover, '小区' if room=='community' else room, 'cover', 3.0)
        for room,slot in [('客厅','living'),('阳台','living'),('厨房','kitchen_bath'),
                          ('卫生间','kitchen_bath'),('卧室','bedrooms'),('其他','bedrooms')]:
            for p in self._claim_many(self.groups.get(room),2 if room=='卧室' else 1,'tour '+room):
                add(p,room,slot)
        community=self._claim_one(self.groups.get('community'),'tour community')
        if community:add(community,'小区','community')
        plan=self._claim_one(self.groups.get('floorplan'),'tour plan')
        if plan:add(plan,'户型','floorplan',3.6,3.2)
        else:
            add(None,'房源资料','end',3.2,3.0)
            shots[-1]['kind']='end'
        order=self.shot_order()
        shots.sort(key=lambda s:order.index(s['slot']))
        return shots,self._story_sections(shots)

    def _story_sections(self, shots):
        """Reindex after pruning, so timing, previews and SFX share one sequence."""
        sections, elapsed = [], 0.0
        for shot in shots:
            if not sections or sections[-1]['template'] != shot['slot']:
                sections.append(dict(template=shot['slot'], start=elapsed, duration=0.0))
            shot['index'] = f'{len(sections):02d}'
            sections[-1]['duration'] += shot['dur']
            elapsed += shot['dur']
        return sections

    def _story_timeline(self):
        """Interior first; category-based selection, never visual/LLM claims."""
        shots = []

        def add(items, label, slot, planned, minimum, hero=False, meta=()):
            shot = self._timed(dict(kind='collage' if len(items) > 1 else 'band',
                label=label, title=label, slot=slot, plate=f'story_{len(shots)}',
                photos=items, hero=hero, meta=list(meta)), (planned, minimum, planned + 1.0))
            shot['read_min'] = minimum
            shots.append(shot)
            return shot

        pool = [p for key in ('客厅', '卧室', '阳台', '厨房', '卫生间', '其他')
                for p in self.groups.get(key, [])]
        cover = self._claim_one(pool or self.groups.get('community'), 'story cover')
        if cover:
            add([cover], '封面', 'cover', 2.6, 2.4, hero=True)
        plan = self._claim_one(self.groups.get('floorplan'), 'story plan')
        if plan:
            add([plan], '户型', 'floorplan', 3.2, 3.0)
        for key, slot in [('客厅', 'living'), ('阳台', 'living'),
                          ('厨房', 'kitchen_bath'), ('卫生间', 'kitchen_bath'),
                          ('卧室', 'bedrooms'), ('其他', 'bedrooms')]:
            items = self._claim_many(self.groups.get(key), 4 if key == '卧室' else 1, 'story ' + key)
            while items:
                pair = len(items) > 1 and all(p[1].width / p[1].height >= 1.1 for p in items[:2])
                batch, items = items[:2 if pair else 1], items[2 if pair else 1:]
                # Whole-listing tags are not evidence about this particular room.
                add(batch, key, slot, 2.5 if pair else 3.0, 2.2 if pair else 2.4)
        community = self._claim_one(self.groups.get('community'), 'story environment')
        if community:
            year = self.year if not self.year or self.year.endswith('年') else self.year + '年'
            facts = [v for v in (year + '建成' if year else '',
                                '绿化率' + self.green if self.green else '') if v]
            add([community], '小区环境', 'community', 2.8, 2.4, meta=facts)
        # No redundant blank recap for a single photo with very little data.
        if len(self._story_cards()) >= 2 or self.cta or not shots:
            spare = self._claim_one(self.groups.get('community'), 'story closing photo')
            end = add([spare] if spare else [], '关键数据', 'end', 3.4, 3.2)
            end['kind'] = 'end'
        return shots, self._story_sections(shots)

    def _story_cards(self):
        floor = self.floor
        if self.total_floors:
            floor = dot_join([floor, '共' + self.total_floors])
        candidates = [('建筑面积', self.area), ('套内面积', self.inner_area),
                      ('单价', self.unit), ('楼层', floor), ('户型', self.layout_full),
                      ('朝向', self.orientation), ('装修', self.decoration)]
        return [(label, value) for label, value in candidates if value][:4]

    def _editorial_mobile_photos(self, shots):
        """02: pair related landscapes, reserve an unused photograph for the end.

        Pairing changes picture allocation; single-view sweeps get more time.
        The selected music still determines the final, complete duration.
        Every picture still belongs to exactly one shot; other templates retain
        their existing allocation.
        """
        def photos(shot):
            return shot.get('photos') or ([shot['photo']] if shot.get('photo') else [])

        def assign(shot, items):
            shot.pop('photo', None)
            shot['photos'] = list(items)
            shot['files'] = [p[0] for p in items]
            if shot['kind'] != 'end':
                shot['kind'] = 'collage' if len(items) > 1 else 'band'

        # Four bedroom pictures read better as two large pairs than 1 + 3 tiles.
        bedrooms = [s for s in shots if s.get('label') == '卧室']
        pool = [p for s in bedrooms for p in photos(s)]
        if len(bedrooms) == 2 and len(pool) == 4 and all(p[1].width / p[1].height >= 1.1 for p in pool):
            assign(bedrooms[0], pool[:2])
            assign(bedrooms[1], pool[2:])
        # Three landscapes cannot fill a portrait page without either tiny
        # secondary tiles or heavy crop. Use two; the spare can close the video.
        for shot in shots:
            items = photos(shot)
            if len(items) > 2 and all(p[1].width / p[1].height >= 1.1 for p in items):
                assign(shot, items[:2])
        # Portraits retain their height on separate pages instead of shrinking
        # several tall rooms into a short horizontal strip. Preserve slot time.
        expanded = []
        for shot in shots:
            items = photos(shot)
            if len(items) > 1 and any(p[1].width / p[1].height < 1.1 for p in items):
                for item in items:
                    single = dict(shot)
                    assign(single, [item])
                    for key in ('dur', 'dur_plan', 'dur_lo', 'dur_hi'):
                        single[key] = shot[key] / len(items)
                    expanded.append(single)
            else:
                expanded.append(shot)
        shots[:] = expanded
        self.used_files = {p[0] for s in shots for p in photos(s)}
        first = shots[0]
        items = photos(first)
        if len(items) == 1 and first.get('label') != '户型' and items[0][1].width >= items[0][1].height:
            same_group = next((ps for key, ps in self.groups.items() if key != 'floorplan'
                               and any(p[0] == items[0][0] for p in ps)), [])
            spare = self._claim_one([p for p in same_group if p[0] not in self.used_files
                                    and p[1].width / p[1].height >= 1.1], '02封面第二视角')
            if spare:
                assign(first, items + [spare])
        end = next((s for s in shots if s['kind'] == 'end'), None)
        if end is not None:
            spare = self._claim_one([p for key, ps in self.groups.items() if key != 'floorplan'
                                    for p in ps if p[0] not in self.used_files], '02封底照片')
            if spare:
                assign(end, [spare])
            elif len(shots) > 1 and len(self.end_rows()) <= 3:
                # A sparse recap would repeat the cover on an otherwise empty
                # screen. Finish on the last photograph instead.
                shots.remove(end)
        # A lateral sweep needs time to show both edges of a landscape.
        for shot in shots:
            items = photos(shot)
            if shot.get('label') == '户型':
                self._timed(shot, (2.6, 2.2, 3.2))
            elif shot['kind'] != 'end' and len(items) == 2:
                self._timed(shot, (2.4 if shot is shots[0] else 2.2, 2.0, 3.0))
            elif (shot['kind'] != 'end' and len(items) == 1
                    and items[0][1].width / items[0][1].height >= 1.1):
                self._timed(shot, (3.4, 2.4, 4.2))

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
        if region.get('framing') == 'full-pan':
            # Hold each edge during the transition and long enough to read the
            # space. The continuous sweep covers every source pixel over time.
            q = min(1.0, max(0.0, (p - .20) / .60))
            e = .5 - .5 * math.cos(math.pi * q)
            return src, ((sw - bw) * e, 0.0, bw, float(sh))
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
        # Sub-pixel affine sampling (BILINEAR for high-speed video rendering without visible loss):
        resample = Image.Resampling.BICUBIC if getattr(self, 'kb_resample', '') == 'bicubic' else Image.Resampling.BILINEAR
        return src.transform((w, h), Image.Transform.AFFINE,
                             (cw / w, 0, x0, 0, ch / h, y0), resample=resample)

    def compose(self, shot, p, pulse=1.0, text_progress=1.0, local_time=None):
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
                canvas.paste(self.kb_render(region, p, pulse), region['rect'][:2], region.get('mask'))
            base = np.asarray(canvas)
        if lay.get('text_events') and local_time is not None and self.variation != 'off':
            # Cache small transparent text sprites, not full-frame overlays per
            # animation step. Static plates still show the completed composition.
            canvas = Image.fromarray(base).copy()
            if lay.get('fixed_overlay') is not None:
                canvas.paste(lay['fixed_overlay'], (0,0), lay['fixed_overlay'])
            for event in lay['text_events']:
                progress = (local_time-event['delay']) / event['duration']
                if progress < 0:
                    continue
                e = min(1.0,max(0.0,progress))
                e = 1-(1-e)**3
                sprite = event['image']
                x,y,r,bottom = event['rect']
                if event['effect'] == 'pop':
                    scale = .90 + .10*e
                    w,h = max(1,round(sprite.width*scale)),max(1,round(sprite.height*scale))
                    sprite = sprite.resize((w,h),Image.Resampling.LANCZOS)
                    x += (r-x-w)//2
                    y += (bottom-y-h)//2
                else:
                    y += round(event['offset']*(1-e))
                alpha = event['initial_alpha']+(1-event['initial_alpha'])*e
                if alpha < 1:
                    sprite = sprite.copy()
                    sprite.putalpha(sprite.getchannel('A').point([round(v*alpha) for v in range(256)]))
                canvas.paste(sprite,(x,y),sprite)
            return canvas
        tb, inv = lay['tb'], lay['inv']
        if text_progress < 1 and shot['text_animation']['effect'] != 'none':
            e = max(0.0, text_progress)
            e = e * e * (3 - 2 * e)
            effect = shot['text_animation']['effect']
            alpha = 255 - inv
            if effect == 'rise':
                dy = round(shot['text_animation']['offset'] * (1 - e))
                shifted_tb, shifted_alpha = np.zeros_like(tb), np.zeros_like(alpha)
                if dy:
                    shifted_tb[dy:] = tb[:-dy]
                    shifted_alpha[dy:] = alpha[:-dy]
                    tb, alpha = shifted_tb, shifted_alpha
            elif effect == 'reveal':
                alpha, tb = alpha.copy(), tb.copy()
                edge = round(W * e)
                alpha[:, edge:] = 0
                tb[:, edge:] = 0
            tb = (tb * e).astype(np.uint16)
            inv = 255 - (alpha * e).astype(np.uint16)
        out = (base.astype(np.uint16) * inv + 127) // 255 + tb
        return Image.fromarray(np.minimum(out, 255).astype(np.uint8), 'RGB')

    def shot_frame(self, index, local, pulse=1.0):
        shot = self.shots[index]
        pre, post = shot.get('_pre', 0.0), shot.get('_post', 0.0)
        span = shot['dur'] + pre + post
        anim = shot['text_animation']
        progress = 1.0
        if anim['effect'] != 'none':
            # Remain stable during the incoming transition, then animate the text.
            progress = max(0.0, min(1.0, (local - pre) / anim['duration']))
        return self.compose(shot, (local + pre) / span if span > 0 else 0.0, pulse, progress,
                            local_time=max(0.0,local-pre))

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

    def fit_to_music(self, duration, downbeats=(), phrase_onsets=(), window=0.40):
        """Retime pictures to the full clip; music start and end stay fixed.

        Spread extra time over photos, keeping the end card at its original
        length. Short clips compress all shots with a readable minimum. Beat
        snapping only moves interior cuts; it never changes the final endpoint.
        """
        if self.template_name in NARRATIVE_TEMPLATES:
            return self._fit_story_to_music(duration, downbeats, phrase_onsets, window)
        minimum = max(0.60, 2.0 / self.fps)
        if not math.isfinite(duration) or duration < len(self.shots) * minimum:
            raise ValueError(f'Music is too short ({duration:.3f}s) for {len(self.shots)} shots '
                             f'at {self.fps} fps; need at least {len(self.shots) * minimum:.3f}s')
        plans = np.array([float(s['dur_plan']) for s in self.shots])
        if duration >= float(plans.sum()):
            weights = np.array([p if s['kind'] != 'end' else 0.0
                                for s, p in zip(self.shots, plans)])
            if not weights.any():
                weights = plans.copy()
            durations = plans + (duration - plans.sum()) * weights / weights.sum()
        else:
            weights = np.maximum(plans - minimum, 0.0)
            if not weights.any():
                weights = np.ones(len(plans))
            durations = minimum + (duration - len(plans) * minimum) * weights / weights.sum()
        ends = list(np.cumsum(durations))
        ends[-1] = float(duration)
        planned = ends.copy()
        phrases = sorted(float(t) for t in phrase_onsets if 0 < t < duration)
        bars = sorted(float(t) for t in downbeats if 0 < t < duration)
        snaps = []
        for i in range(len(ends) - 1):
            prev = ends[i - 1] if i else 0.0
            kind, target = 'hold', None
            for label, grid in (('phrase', phrases), ('bar', bars)):
                if (i == len(ends) - 2 and self.shots[-1]['kind'] == 'end'
                        and duration >= float(plans.sum())):
                    break  # Keep the unextended end card at its original length.
                candidates = [t for t in grid if abs(t - planned[i]) <= window
                              and prev + minimum <= t <= ends[i + 1] - minimum]
                if candidates:
                    target = min(candidates, key=lambda t: abs(t - planned[i]))
                    ends[i], kind = target, label
                    break
            if phrases or bars:
                snaps.append(dict(index=i, planned=round(planned[i], 4), time=round(ends[i], 4),
                                  delta=round(ends[i] - planned[i], 4), hit=kind,
                                  target=target, distance=0.0 if target is not None else None))
        self.beat_deltas = [round(t - p, 4) for t, p in zip(ends[:-1], planned[:-1])]
        self.phrase_snaps = snaps
        start = 0.0
        sections = {}
        for shot, end in zip(self.shots, ends):
            shot['dur_source_plan'] = shot['dur_plan']
            shot['dur'] = shot['dur_plan'] = end - start
            # These are the effective bounds for the music-driven timeline.
            shot['dur_lo'], shot['dur_hi'] = minimum, shot['dur']
            sec = sections.setdefault(shot['index'], [start, 0.0])
            sec[1] += shot['dur']
            start = end
        for sec, (start, length) in zip(self.sections, sections.values()):
            sec['start'], sec['duration'] = start, length
        self.duration = float(duration)
        self.cache = {k: v for k, v in self.cache.items()
                      if not (isinstance(k, tuple) and k and k[0] in ('kbsrc', 'layers'))}
        self.plates = {}
        self.assign_motion(self._transitions, self._transition_dur)

    def _fit_story_to_music(self, duration, downbeats, phrase_onsets, window):
        """Preserve reading floors; remove secondary shots before squeezing text."""
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Music duration must be finite and positive')
        minimum = lambda s: max(s['read_min'], 2.0 / self.fps)
        # Work on a copy: an impossible duration must not partially alter a reel.
        shots = list(self.shots)
        removed = []
        while sum(minimum(s) for s in shots) > duration + 1e-8:
            removable = [s for s in shots[1:] if s['slot'] not in ('floorplan', 'end')]
            if not removable:
                raise ValueError(f'Music is too short ({duration:.3f}s) for the essential '
                                 f'pages; need {sum(minimum(s) for s in shots):.3f}s')
            # Keep the opening and all reading pages; trim extra room angles first.
            victim = next((s for s in reversed(removable)
                           if sum(t['label'] == s['label'] for t in shots) > 1), None)
            victim = victim or next((s for s in removable if s['slot'] == 'community'), removable[-1])
            shots.remove(victim)
            removed.append(victim)
        self.shots = shots
        for shot in removed:
            self.skipped.append('Music budget: omitted ' + ', '.join(shot['files']))
        floors = np.array([minimum(s) for s in shots])
        plans = np.array([max(minimum(s), float(s['dur_plan'])) for s in shots])
        if duration >= plans.sum():
            weights = np.array([p if s['kind'] != 'end' else 0.0 for s, p in zip(shots, plans)])
            if not weights.any():
                weights = plans.copy()
            durations = plans + (duration - plans.sum()) * weights / weights.sum()
        else:
            weights = plans - floors
            if not weights.any():
                weights = np.ones(len(shots))
            durations = floors + (duration - floors.sum()) * weights / weights.sum()
        ends = list(np.cumsum(durations))
        ends[-1] = float(duration)
        planned, snaps = ends.copy(), []
        for i in range(len(ends) - 1):
            prev = ends[i - 1] if i else 0.0
            hit, target = 'hold', None
            # A long track does not inflate the closing card or steal its hold.
            fixed_end = i == len(ends) - 2 and shots[-1]['kind'] == 'end' and duration >= plans.sum()
            if not fixed_end:
                for label, grid in (('phrase', phrase_onsets), ('bar', downbeats)):
                    candidates = [float(t) for t in grid if math.isfinite(float(t))
                                  and abs(float(t) - planned[i]) <= window
                                  and prev + floors[i] <= float(t) <= ends[i + 1] - floors[i + 1]]
                    if candidates:
                        target = min(candidates, key=lambda t: abs(t - planned[i]))
                        ends[i], hit = target, label
                        break
            snaps.append(dict(index=i, planned=round(planned[i], 4), time=round(ends[i], 4),
                              delta=round(ends[i] - planned[i], 4), hit=hit, target=target,
                              distance=0.0 if target is not None else None))
        start = 0.0
        for shot, end, floor in zip(shots, ends, floors):
            shot['dur_source_plan'] = shot['dur_plan']
            shot['dur'] = shot['dur_plan'] = end - start
            shot['dur_lo'], shot['dur_hi'] = float(floor), shot['dur']
            start = end
        self.sections = self._story_sections(shots)
        self.duration = float(duration)
        self.phrase_snaps = snaps
        self.beat_deltas = [round(t - p, 4) for t, p in zip(ends[:-1], planned[:-1])]
        self.used_files = {f for s in shots for f in s['files']}
        self.cache.clear()
        self.plates.clear()
        self.assign_motion(self._transitions, self._transition_dur)

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
        rng = random.Random(derived_seed(self.seed, 'transitions') if self.variation == 'subtle' else self.seed)
        if spec in ('random', 'rand'):
            # Deal the pool without replacement so a short film shows the set,
            # then reshuffle. The seed is stable; the previous kind never repeats.
            bag = []
            plan = []
            prev = None
            light_used = False
            while len(plan) < n:
                if not bag:
                    bag = [t for t in self.transition_pool
                           if not (self.variation == 'subtle' and light_used and t == 'light_leak')]
                    rng.shuffle(bag)
                    if prev is not None and bag[0] == prev and len(bag) > 1:
                        bag[0], bag[1] = bag[1], bag[0]
                kind = bag.pop(0)
                light_used = light_used or kind == 'light_leak'
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
        motion_rng = random.Random(derived_seed(self.seed, 'motion'))
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
            if self.variation == 'subtle':
                if shot.get('label') == '户型':
                    shot['kb'], shot['kb_strength'] = None, 0.0
                else:
                    shot['kb'] = motion_rng.choice(['push_in', 'pull_out', 'pan_lr', 'pan_rl'])
                    shot['kb_strength'] = round(motion_rng.uniform(0.02, 0.04), 4)

        if self.template_name in MOBILE_LAYOUTS:
            for shot in self.shots:
                photos = shot.get('photos') or ([shot['photo']] if shot.get('photo') else [])
                sweep = (self.kenburns and shot['kind'] != 'end' and shot.get('label') != '户型'
                         and len(photos) == 1 and photos[0][1].width / photos[0][1].height >= 1.1)
                shot['kb'], shot['kb_strength'] = ('full_pan' if sweep else None), 0.0

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
                if varied and self.variation == 'subtle':
                    rng = random.Random(derived_seed(self.seed, f'transition-duration:{k}'))
                    lower = max(0.34, floor)
                    dur = rng.uniform(lower, max(lower, min(0.40, self._transition_dur)))
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
        if self.template_name in MOBILE_LAYOUTS:
            return out
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
        strength = (0.65 if self.variation == 'subtle' else 1.65) * math.sin(math.pi * max(p, 0.0))
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
        blur = 0 if self.template_name in MOBILE_LAYOUTS else int(round(52 * min(1.0, vel / 1.5)))
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
            if self.template_name in MOBILE_LAYOUTS:
                edge = max(0, min(W, round(e * W)))
                out = a.copy()
                if edge:
                    out.paste(b.crop((0, 0, edge, H)), (0, 0))
                return out
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
                allowed = [f for f in fallbacks if not (self.variation == 'subtle' and f == 'light_leak'
                           and any(c['type'] == 'light_leak' for j, c in enumerate(self.cuts) if j != k))]
                options = [f for f in allowed if f != old and f not in (prev_t, next_t)] or \
                    ['zoom' if 'zoom' not in (prev_t, next_t) else 'fade']
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
            # Large ivory/black information fields must not dilute the visible
            # photo transition. Score only genuinely changing pixels in subtle
            # mode, while retaining the original v10 proof in variation=off.
            active = np.mean(np.abs(B-A), axis=2) > 12
            if self.variation == 'subtle' and np.mean(active) >= .01:
                A, M, B = A[active], M[active], B[active]
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
