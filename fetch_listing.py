#!/usr/bin/env python3
"""Fetch a Beike listing (data + photos) via the Beike MCP, no LLM.

    fetch_listing.py <house_id> [--out-dir DIR] [--city 广州] [--type auto|sale|rent] [--force]

Writes into DIR (default data/ke-house-<id>):
  raw_house_detail.txt / raw_resblock_detail.txt   entity_detail responses (verbatim)
  raw_house_material.json / raw_resblock_material.json   entity_material responses
  listing.json / manifest.json   same schema build_slideshow.py already reads
  images/NN_<room>_<k>.jpg       highest resolution available, deduped by sha1
Exit codes: 0 ok, 2 bad args / no key, 3 MCP/network failure, 4 listing not found, 5 no images.
"""
import argparse, hashlib, io, json, re, sys, time, urllib.request, urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import beike_mcp  # noqa: E402

CITIES = ['广州', '北京', '上海', '深圳', '杭州', '成都', '天津', '武汉', '南京', '重庆', '苏州',
          '西安', '长沙', '郑州', '佛山', '东莞', '青岛', '合肥', '厦门', '济南']
COMMUNITY_MAX = 6
KEY_ROOMS = ['小区', '户型图', '客厅', '卧室', '厨房', '卫生间']
ROOM_LABEL = {'其他': '其他'}


def log(*a):
    msg = beike_mcp.redact(' '.join(str(x) for x in a))
    print('[fetch]', msg, file=sys.stderr, flush=True)


# Tags that wrap the document, not an entity payload.
_SKIP_TAGS = {'metadata', '参考数据', '贝壳召回知识', '可选召回字段', '卡片依赖的实体id信息'}


def parse_detail(text):
    """entity_detail returns pseudo-XML wrapping JSON blocks: <ID>\n{...}\n</ID>."""
    if isinstance(text, dict):
        # Some servers return a map of id -> object instead of the XML wrapper.
        if any(isinstance(v, dict) for v in text.values()):
            return {str(k): v for k, v in text.items() if isinstance(v, dict) and str(k) not in _SKIP_TAGS}
        text = json.dumps(text, ensure_ascii=False)
    out, dec = {}, json.JSONDecoder()
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    for m in re.finditer(r'<([^<>/\n]+)>\s*\{', text):
        tag = m.group(1).strip()
        if tag in _SKIP_TAGS:
            continue
        try:
            obj, _ = dec.raw_decode(text, m.end() - 1)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.setdefault(tag, obj)
    return out


def parse_material(res):
    if isinstance(res, dict):
        return res
    text = str(res or '')
    text = text.split('<metadata>')[0].strip()
    try:
        return json.loads(text)
    except ValueError:
        return {}


def upgrade_urls(url):
    """Candidate URLs, highest resolution first; original last."""
    c = []
    base = url.split('?')[0]
    m = re.match(r'(.*?\.(?:jpg|jpeg|png))(?:\.\d+x\d+\.jpg|!.*)$', base, re.I)
    if 'ljcdn.com' in url and m:
        c.append(m.group(1) + '.1920x1440.jpg?from=ke.com')
    c.append(url)
    return list(dict.fromkeys(c))


def http_get(url, timeout=30, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.ke.com/'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 404):
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.0 * (i + 1))
    raise last or RuntimeError('download failed')


def download_best(url):
    from PIL import Image
    for cand in upgrade_urls(url):
        try:
            data = http_get(cand)
            im = Image.open(io.BytesIO(data))
            im.load()
            return cand, data, im.size
        except Exception:  # noqa: BLE001
            continue
    return None, None, None


class Fetcher:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out_dir).resolve() if args.out_dir else Path(__file__).resolve().parent / 'data' / f'ke-house-{args.house_id}'
        self.client = None

    def mcp(self):
        if self.client is None:
            self.client = beike_mcp.Client().connect()
            names = [t.get('name') for t in self.client.tools()]
            missing = [n for n in ('entity_detail', 'entity_material') if n not in names]
            if missing:
                have = ', '.join(n for n in names if n) or '(none)'
                raise beike_mcp.MCPError(
                    f'MCP tools/list is missing {", ".join(missing)}. Available: {have}')
            self.tools_used = ['entity_detail', 'entity_material']
            log('MCP tools: ' + ', '.join(self.tools_used))
        return self.client

    def cached(self, name):
        p = self.out / name
        return p if p.is_file() and not self.args.force else None

    def cache_ready(self):
        """listing.json + manifest.json with ordered local images already on disk."""
        if self.args.force:
            return False
        listing_path, manifest_path = self.out / 'listing.json', self.out / 'manifest.json'
        if not listing_path.is_file() or not manifest_path.is_file():
            return False
        try:
            man = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        except ValueError:
            return False
        if not isinstance(man, dict):
            return False
        images = [i for i in (man.get('ordered_images') or []) if isinstance(i, dict)]
        usable = [i for i in images if i.get('role') != 'vr_cover']
        if not usable:
            return False
        return all((self.out / (i.get('rel_path') or '')).is_file() or Path(i.get('path') or '').is_file() for i in usable)

    def detail(self, ids, etype, city):
        return self.mcp().call('entity_detail', {'entity_ids': ids, 'entity_type': etype, 'city_name': city})

    def find_house(self):
        """Return (city, entity_type, raw_text, blocks). Queries --city; scans other cities only with --scan-cities."""
        hid = self.args.house_id
        types = {'auto': ['house', 'rent_house'], 'sale': ['house'], 'rent': ['rent_house'], 'new': ['house']}[self.args.type]
        p = self.cached('raw_house_detail.txt')
        meta = self.out / 'raw_fetch_meta.json'
        if p and meta.is_file():
            m = json.loads(meta.read_text(encoding='utf-8-sig'))
            if m.get('house_id') == hid and m.get('city') == self.args.city and m.get('entity_type') in types:
                txt = p.read_text(encoding='utf-8-sig')
                return m['city'], m['entity_type'], txt, parse_detail(txt)
        cities = [self.args.city]
        if self.args.scan_cities:
            cities += [c for c in CITIES if c != self.args.city]
        for etype in types:
            for city in cities:
                txt = self.detail(hid, etype, city)
                blocks = parse_detail(txt if isinstance(txt, str) else json.dumps(txt, ensure_ascii=False))
                if hid in blocks:
                    log(f'found {hid} as {etype} in {city}')
                    raw = txt if isinstance(txt, str) else json.dumps(txt, ensure_ascii=False)
                    (self.out / 'raw_house_detail.txt').write_text(beike_mcp.redact(raw), encoding='utf-8')
                    meta.write_text(json.dumps({'city': city, 'entity_type': etype, 'house_id': hid}, ensure_ascii=False), encoding='utf-8')
                    return city, etype, txt, blocks
                if self.args.city and city == self.args.city and len(cities) > 1:
                    log(f'not found in {city}, scanning other cities...')
        return None, None, None, {}

    def material(self, name, eid, etype, city, fields):
        p = self.cached(name)
        if p:
            return json.loads(p.read_text(encoding='utf-8-sig'))
        try:
            data = parse_material(self.mcp().call('entity_material', {
                'entity_ids': eid, 'entity_type': etype, 'city_name': city, 'fields': fields}))
        except beike_mcp.MCPError as e:
            log(f'material {etype}/{fields} failed: {e}')
            data = {}
        if data:
            (self.out / name).write_text(beike_mcp.redact(json.dumps(data, ensure_ascii=False, indent=2)), encoding='utf-8')
        return data

    def run(self):
        hid = self.args.house_id
        self.out.mkdir(parents=True, exist_ok=True)
        if self.cache_ready():
            log(f'cache hit: {self.out} (use --force to refetch)')
            return 0
        city, etype, txt, blocks = self.find_house()
        if not blocks.get(hid):
            log(f'listing {hid} not found on Beike (tried cities: {self.args.city or "all"}). Try --city <城市>.')
            return 4
        house = blocks[hid]
        hb = house.get('基础信息') or house.get('基本信息') or {}
        rid = str(hb.get('小区ID') or '')
        rb = {}
        for k, v in blocks.items():
            if k == hid or not isinstance(v, dict):
                continue
            info = v.get('基本信息') if isinstance(v.get('基本信息'), dict) else {}
            cid = str(info.get('小区ID') or '')
            if rid and cid == rid:
                rb, rid = info, cid
                break
            if not rid and (info.get('小区名称') or cid):
                rb, rid = info, cid
                break
        (self.out / 'raw_resblock_detail.json').write_text(
            beike_mcp.redact(json.dumps(rb, ensure_ascii=False, indent=2)), encoding='utf-8')

        mat_type = 'rent_house' if etype == 'rent_house' else 'house'
        hfields = ['房源图', '户型图'] if etype == 'rent_house' else ['房源图片']
        hm = self.material('raw_house_material.json', hid, mat_type, city, hfields)
        rm = self.material('raw_resblock_material.json', rid, 'resblock', city, ['小区图片']) if rid else {}

        listing_type = self.args.type if self.args.type != 'auto' else ('rent' if etype == 'rent_house' else 'sale')
        listing = build_listing(hid, city, hb, rb, rid, listing_type)
        plan = plan_images(hm.get(hid) or {}, rm.get(rid) or {} if rid else {})
        manifest, missing, failed = self.download(plan, listing)
        if not manifest['ordered_images']:
            log('no images could be downloaded')
            return 5
        if not any(i.get('role') == 'community' for i in manifest['ordered_images']):
            log('no community photos; renderer will use available interior photos')
        layout_text = str(listing.get('layout') or '')
        if '厨' not in layout_text:
            missing = [m for m in missing if m != '厨房']
        listing['missing'] = missing
        absent = [k for k in ('price', 'area_sqm', 'layout', 'community', 'orientation', 'floor',
                              'decoration', 'built_year', 'district') if not listing.get(k)]
        listing['missing_fields'] = absent
        listing['source'] = {'tool': 'beike-mcp', 'tools': getattr(self, 'tools_used',
                             ['entity_detail', 'entity_material']),
                             'endpoint': beike_mcp.URL, 'city': city, 'entity_type': etype,
                             'fetched_at': time.strftime('%Y-%m-%d %H:%M:%S')}
        vr_note, vr_skipped = manifest.pop('_vr_note'), manifest.pop('_vr_skipped')
        manifest.update({'missing_rooms': [m for m in missing if m != '小区'],
                         'vr_skipped': vr_skipped, 'failed_downloads': failed,
                         'notes': [f'自动抓取 (fetch_listing.py)；缺失: {"、".join(missing) or "无"}',
                                   vr_note]})
        (self.out / 'listing.json').write_text(beike_mcp.redact(json.dumps(listing, ensure_ascii=False, indent=2)), encoding='utf-8')
        (self.out / 'manifest.json').write_text(beike_mcp.redact(json.dumps(manifest, ensure_ascii=False, indent=2)), encoding='utf-8')
        log(f'ok: {listing["title"]} | {len(manifest["ordered_images"])} images | missing={missing} -> {self.out}')
        return 0

    def download(self, plan, listing):
        img_dir = self.out / 'images'
        img_dir.mkdir(exist_ok=True)
        seen, ordered, failed = {}, [], []
        n = 0
        counters = {}
        vr_state = 'absent'  # absent | downloaded | unavailable
        for item in plan:
            room = item['room']
            optional = bool(item.get('optional'))
            cnt = counters.get(room, 0) + 1
            if room == '户型图':
                stem = '户型图'
            elif room == 'VR':
                stem = 'VR封面'
            else:
                stem = f'{room}_{cnt}'
            name = f'{n:02d}_{stem}.jpg'
            path = img_dir / name
            if path.is_file() and not self.args.force:
                from PIL import Image
                data = path.read_bytes()
                src, size = item['url'], Image.open(io.BytesIO(data)).size
            else:
                src, data, size = download_best(item['url'])
                if not data:
                    if optional:
                        vr_state = 'unavailable'
                        log(f'VR unavailable, skipped: {item["url"].split("?")[0][-60:]}')
                    else:
                        failed.append(item['url'])
                        log(f'download failed: {room}')
                    continue
            h = hashlib.sha1(data).hexdigest()
            if h in seen:
                log(f'dup skipped: {room}')
                continue
            seen[h] = name
            if not path.is_file() or self.args.force:
                path.write_bytes(_as_jpeg(data))
            counters[room] = cnt
            n += 1
            if room == 'VR':
                vr_state = 'downloaded'
            label = item['label'] if cnt == 1 or item['role'] != 'room' else f'{item["label"]} {cnt}'
            ordered.append({'path': str(path), 'rel_path': f'images/{name}', 'label': label,
                            'room': room, 'role': item['role'], 'width': size[0], 'height': size[1],
                            'bytes': path.stat().st_size, 'source_url': src})
            log(f'saved {name} {size[0]}x{size[1]}')
        present = {i['room'] for i in ordered}
        missing = [k for k in KEY_ROOMS if k not in present]
        man = {k: listing.get(k) for k in ('listing_id', 'community', 'title', 'price', 'layout',
                                            'area_sqm', 'district', 'bizcircle')}
        man['ordered_images'] = ordered
        if vr_state == 'downloaded':
            man['_vr_skipped'] = False
            man['_vr_note'] = 'VR封面已下载但未编入主幻灯片（v8 跳过 vr_cover）。'
        elif vr_state == 'unavailable':
            man['_vr_skipped'] = True
            man['_vr_note'] = 'VR 封面不可用或下载失败，已跳过。'
        else:
            man['_vr_skipped'] = True
            man['_vr_note'] = '物料里没有 VR 封面，已跳过。'
        return man, missing, failed


def _as_jpeg(data):
    if data[:3] == b'\xff\xd8\xff':
        return data
    from PIL import Image
    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).convert('RGB').save(buf, 'JPEG', quality=92)
    return buf.getvalue()


def plan_images(hm, rm):
    """Ordered download plan: 小区 (≤6), 户型图, then rooms in API order. VR skipped."""
    plan = []
    rpics = (rm.get('小区图片') or {}).get('图片') or []
    for p in rpics[:COMMUNITY_MAX]:
        if p.get('图片地址'):
            plan.append({'url': p['图片地址'], 'room': '小区', 'role': 'community',
                         'label': '小区外观' if not plan else '小区环境'})
    hp = hm.get('房源图片') or hm
    fp = hp.get('户型图片') or hp.get('户型图')
    if isinstance(fp, list):
        fp = (fp[0] or {}).get('图片地址') if fp and isinstance(fp[0], dict) else (fp[0] if fp else None)
    if fp:
        plan.append({'url': fp, 'room': '户型图', 'role': 'floorplan', 'label': '户型图'})
    rooms = hp.get('房间图片') or hp.get('房源图') or []
    for p in rooms if isinstance(rooms, list) else []:
        if isinstance(p, str):
            p = {'图片地址': p}
        url = p.get('图片地址')
        if not url:
            continue
        room = (p.get('房间名称') or '其他').strip() or '其他'
        plan.append({'url': url, 'room': room, 'role': 'room', 'label': ROOM_LABEL.get(room, room)})
    return plan


def build_listing(hid, city, hb, rb, rid, listing_type):
    g = lambda *ks: next((str(hb[k]) for k in ks if hb.get(k) not in (None, '')), '')  # noqa: E731
    community = g('小区') or rb.get('小区名称', '')
    price = g('总价', '租金', '月租金')
    area = g('建筑面积', '面积')
    layout = g('房型', '户型')
    title = g('房源标题') or ' '.join(x for x in (community, re.sub(r'\d+厨|\d+卫', '', layout).strip(), area, price) if x)
    return {
        'listing_id': hid, 'city': city, 'community': community, 'resblock_id': rid,
        'title': title, 'price': price, 'unit_price': g('单价'), 'layout': layout,
        'area_sqm': area, 'inner_area_sqm': g('套内面积'), 'orientation': g('朝向'),
        'floor': g('房源所属楼层', '楼层'), 'total_floors': g('单元总楼层', '总楼层'),
        'decoration': g('装修类型', '装修'),
        'district': str(rb.get('所属城区') or g('城区')),
        'bizcircle': g('商圈') or str(rb.get('所属商圈') or ''),
        'built_year': g('建成年代') or str(rb.get('建成年代') or ''),
        'tags': g('标签'), 'status': g('房源售卖状态', '状态'), 'listing_time': g('挂牌时间'),
        'listing_type': listing_type,
        'house_basic': hb, 'resblock_basic': rb,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('house_id')
    ap.add_argument('--out-dir', default=None)
    ap.add_argument('--city', default='广州', help='City to query (default 广州). Other cities require --scan-cities.')
    ap.add_argument('--scan-cities', action='store_true', help='Explicitly scan other cities after a miss')
    ap.add_argument('--type', choices=['auto', 'sale', 'new', 'rent'], default='auto')
    ap.add_argument('--force', action='store_true', help='Ignore cached files and refetch everything.')
    args = ap.parse_args()
    if not re.fullmatch(r'\d{6,}', args.house_id):
        log('house_id must be digits'); return 2
    try:
        return Fetcher(args).run()
    except beike_mcp.MCPError as e:
        log(f'Beike MCP failure: {beike_mcp.redact(e)}')
        return 2 if 'Beike API key file' in str(e) else 3


if __name__ == '__main__':
    sys.exit(main())
