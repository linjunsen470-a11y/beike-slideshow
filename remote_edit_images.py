"""Optional paid photo cleanup. Bounded parallel requests, resumable local outputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
from pathlib import Path
import urllib.error

from PIL import Image
from image_edit_api import config, edit


def source_path(house, entry):
    """Prefer portable manifest paths over paths saved on another computer."""
    relative = entry.get('rel_path')
    name = Path(entry.get('path') or relative or '').name
    candidates = ([house / relative] if relative else []) + [house / 'images' / name]
    if entry.get('path'):
        candidates.append(Path(entry['path']))
    return next((p for p in candidates if p.is_file()), candidates[0])


def valid_image(path):
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except (OSError, ValueError, SyntaxError):
        return False


def write_manifest(target, manifest):
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(target)


def choose(entry, path, house):
    entry['path'] = str(path)
    entry['rel_path'] = path.relative_to(house).as_posix()
    with Image.open(path) as im:
        entry['width'], entry['height'] = im.size
    entry['bytes'] = path.stat().st_size


def edit_one(source, output, settings):
    """One request only: no hidden retry, model fallback or repeat charge."""
    temp = output.with_suffix('.tmp')
    try:
        data = edit(source, settings)
        with Image.open(io.BytesIO(data)) as im:
            im.convert('RGB').save(temp, format='PNG')
        temp.replace(output)
        return None
    except urllib.error.HTTPError as exc:
        return f'HTTP {exc.code}'
    except Exception as exc:
        # Server responses and exception messages can contain URLs or credentials.
        return type(exc).__name__
    finally:
        temp.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--house-dir', required=True, type=Path)
    parser.add_argument('--env', type=Path, default=Path(__file__).with_name('.env'))
    parser.add_argument('--model', default='economy', help='economy (Gemini Flash Lite), configured, or an explicit model ID')
    parser.add_argument('--workers', type=int, default=3, help='Concurrent requests, 1–8 (default 3)')
    parser.add_argument('--limit', type=int, default=0, help='Maximum paid requests this run; 0 = all pending photos')
    parser.add_argument('--only', nargs='+', metavar='FILENAME', help='Edit only these original image filenames')
    parser.add_argument('--force', action='store_true', help='Pay to reprocess existing outputs')
    parser.add_argument('--dry-run', action='store_true', help='List pending requests; no API calls or file writes')
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 8 or args.limit < 0:
        parser.error('--workers must be 1–8 and --limit must be non-negative')
    house = args.house_dir.resolve()
    try:
        manifest = json.loads((house / 'manifest.json').read_text(encoding='utf-8-sig'))
        settings = config(args.env, args.model, require_key=False)
        entries = manifest['ordered_images']
        destination = house / 'images_remote'
        jobs, reused, seen = [], 0, set()
        available = {source_path(house, entry).name for entry in entries}
        if args.only and set(args.only) - available:
            parser.error('--only contains filenames absent from manifest.json')
        for entry in entries:
            source = source_path(house, entry).resolve()
            if not source.is_relative_to(house) or not source.is_file():
                raise ValueError('Manifest source must be an existing file inside --house-dir')
            output = destination / (source.stem + '.png')
            if output in seen:
                raise ValueError('Manifest contains duplicate output names')
            seen.add(output)
            skip = entry.get('role') in ('floorplan', 'vr_cover') or '户型' in (str(entry.get('label', '')) + source.name)
            cached = not skip and valid_image(output) and output.stat().st_mtime >= source.stat().st_mtime
            choose(entry, output if cached else source, house)
            if cached:
                reused += 1
            if skip or (args.only and source.name not in args.only):
                continue
            if (args.force or not cached) and (not args.limit or len(jobs) < args.limit):
                jobs.append((entry, source, output))
    except (OSError, ValueError, KeyError, TypeError):
        parser.error('Cannot read inputs/config; check manifest paths and image-edit settings (credentials are not logged).')
    print(f"Model={settings['IMAGE_EDIT_MODEL']}; requests={len(jobs)}; reused={reused}; workers={args.workers}", flush=True)
    if args.dry_run:
        for _, source, _ in jobs:
            print(source.name)
        return 0
    if jobs and not settings['IMAGE_EDIT_API_KEY']:
        parser.error('Missing IMAGE_EDIT_API_KEY; fill .env.')
    destination.mkdir(exist_ok=True)
    target = house / 'manifest_remote.json'
    write_manifest(target, manifest)
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        pending = {executor.submit(edit_one, source, output, settings): (entry, source, output)
                   for entry, source, output in jobs}
        for future in as_completed(pending):
            entry, source, output = pending[future]
            error = future.result()
            if error:
                failures += 1
                print(f'Failed {source.name}: {error}; keeping previous image/original', flush=True)
            else:
                choose(entry, output, house)
                print(f'Edited {source.name}', flush=True)
            write_manifest(target, manifest)
    print(f'Saved {target}; requests={len(jobs)}, failures={failures}', flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
