"""Dump every shot's static plate + a contact sheet (preview only, no video)."""
import json, sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib, build_slideshow as b
root = Path('/workspace/ke-house-108405507493')
out = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'video/v4d_plates'
out.mkdir(parents=True, exist_ok=True)
listing = json.loads((root / 'listing.json').read_text())
manifest = json.loads((root / 'manifest.json').read_text())
mag = b.Magazine(listing, b.load_assets(manifest, root / 'images'), b.SERIF_PATH, '')
names = []
for i, s in enumerate(mag.shots):
    tag = s.get('plate') or ('hero' if s.get('hero') else 'floorplan' if s.get('label') == '户型' else s.get('title'))
    p = out / f'{i:02d}_{s["kind"]}_{tag}.png'
    mag.plate(s).save(p); names.append(p); print(p)
tw, th, gap = 250, 444, 12
ims = [Image.open(p) for p in names]
sheet = Image.new('RGB', (len(ims) * tw + (len(ims) + 1) * gap, th + 2 * gap), '#1a1a1a')
for k, im in enumerate(ims):
    sheet.paste(im.resize((tw, th), Image.Resampling.LANCZOS), (gap + k * (tw + gap), gap))
sheet.save(out / 'contact.png'); print(out / 'contact.png', sheet.size)
