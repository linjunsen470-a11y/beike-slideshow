"""Create one contact sheet from local photos; no API calls or video encoding."""
import argparse
import json
from pathlib import Path
from PIL import Image
from slideshow_common import load_assets, resolve_font_profile, resolve_template_name
from slideshow_engine import Magazine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--house-dir', type=Path, required=True)
    parser.add_argument('--template', default='ad_photo_story_v20')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--font', default='heiti')
    parser.add_argument('--edited', action='store_true')
    parser.add_argument('--output', '--out', type=Path)
    args = parser.parse_args()
    house = args.house_dir.resolve()
    listing = json.loads((house / 'listing.json').read_text(encoding='utf-8-sig'))
    manifest = json.loads((house / ('manifest_remote.json' if args.edited else 'manifest.json')).read_text(encoding='utf-8-sig'))
    template, seed = resolve_template_name(args.template, args.seed, listing.get('listing_id'))
    fonts = resolve_font_profile(args.font, seed)
    magazine = Magazine(listing, load_assets(manifest, house / ('images_remote' if args.edited else 'images')),
                        fonts['title_path'], template=template, seed=seed, font_profile=fonts)
    shots = magazine.shots
    if not shots:
        parser.error('No photos to preview')
    width, height, columns = 270, 480, min(4, len(shots))
    sheet = Image.new('RGB', (columns * width, ((len(shots) + columns - 1) // columns) * height), '#242424')
    for i, shot in enumerate(shots):
        plate = magazine.plate(shot).resize((width, height), Image.Resampling.LANCZOS)
        sheet.paste(plate, ((i % columns) * width, (i // columns) * height))
    output = args.output or house / 'video' / f'{template}_preview.jpg'
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    print(output)


if __name__ == '__main__':
    main()
