#!/usr/bin/env python3
"""Cross-platform one-command fetch/render entry point (no LLM calls)."""
import argparse
from pathlib import Path
import re
import secrets
import subprocess
import sys


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('house_id')
    parser.add_argument('--work-dir', type=Path,
                        default=here / 'data')
    parser.add_argument('--skip-fetch', action='store_true')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--city', default='广州')
    parser.add_argument('--scan-cities', action='store_true', help='Try other cities if the requested city has no match')
    parser.add_argument('--type', choices=['auto', 'sale', 'new', 'rent'], default='auto')
    parser.add_argument('--seed', type=int)
    parser.add_argument('--template', default='random')
    parser.add_argument('--edited', action='store_true', help='Use existing manifest_remote.json (never calls image AI)')
    args, render_args = parser.parse_known_args()
    if not re.fullmatch(r'\d{6,}', args.house_id):
        parser.error('house_id must contain at least six digits')
    house = args.work_dir.resolve() / ('ke-house-' + args.house_id)
    python = [sys.executable, '-X', 'utf8', '-B', '-u']
    if not args.skip_fetch:
        cmd = python + [str(here / 'fetch_listing.py'), args.house_id, '--out-dir', str(house),
                        '--city', args.city, '--type', args.type]
        if args.force:
            cmd.append('--force')
        if args.scan_cities:
            cmd.append('--scan-cities')
        result = subprocess.run(cmd)
        if result.returncode:
            return result.returncode
    if args.edited:
        manifest = house / 'manifest_remote.json'
        if not manifest.is_file():
            parser.error('--edited requires an existing manifest_remote.json; run remote_edit_images.py first')
        render_args = ['--manifest', str(manifest), '--media-dir', str(house / 'images_remote')] + render_args
    seed = args.seed if args.seed is not None else secrets.randbelow(2147483646) + 1
    print(f'[make_video] template={args.template} seed={seed} house={house}', flush=True)
    return subprocess.run(python + [str(here / 'build_slideshow.py'), '--house-dir', str(house),
                          '--template', args.template, '--seed', str(seed)] + render_args).returncode


if __name__ == '__main__':
    raise SystemExit(main())
