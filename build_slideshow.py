#!/usr/bin/env python3
"""Render local listing photos into a vertical video. No fetching or AI calls."""
import argparse
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import bgm_tools
import sfx_tools
from slideshow_engine import Magazine
from slideshow_common import RECOMMENDED_TEMPLATES
from slideshow_common import (
    AD_TEMPLATES, BGM_LIBRARY, BGM_USER, DEMO_AB_TEMPLATES, H,
    Image, ImageFont, MOBILE_LAYOUTS, MOBILE_TEMPLATES,
    RANDOM_POOL, REFERENCE_TEMPLATES, SANS_BOLD_PATH, SERIF_PATH, SOFT_BGM,
    STORY_TEMPLATE, TEMPLATE_ORDER, TRANSITIONS, V14_LABELS, V14_TEMPLATES,
    W, derived_seed, load_assets,
    resolve_font_profile, resolve_template_name, shot_label,
    slot_sequence,
)

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
        listing = json.loads(Path(args.listing).read_text(encoding='utf-8-sig'))
    manifest = {}
    if args.manifest and Path(args.manifest).is_file():
        manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8-sig'))
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


def select_bgm(args, listing):
    """Choose music before constructing the picture timeline."""
    if args.bgm_file:
        return {'path': str(args.bgm_file), 'title': args.bgm_file.stem}, False
    choice = args.bgm.strip()
    if choice.lower() in ('no', 'off', 'none'):
        return None, False
    fallback = False
    if choice.lower() in ('auto', 'yes', 'random'):
        user_tracks = bgm_tools.list_tracks(BGM_USER)
        fallback = not bool(user_tracks)
        folders = [BGM_LIBRARY] if fallback else [BGM_USER]
        print('BGM source: ' + ('bgm/user has no eligible clips; using bgm/library' if fallback
                               else f'bgm/user ({len(user_tracks)} clips shorter than 21s)'), flush=True)
        prefer = SOFT_BGM if fallback and not args.bgm_track else None
        # BGM Gacha: true random choice every time unless user explicitly locked with --seed and did not use random
        if not getattr(args, 'explicit_seed', False) or choice.lower() == 'random' or getattr(args, 'bgm_random', False):
            seed = None
        else:
            seed = derived_seed(args.seed, 'music') if args.variation == 'subtle' else args.seed
    elif Path(choice).is_dir():
        folders, prefer = [Path(choice)], None
        seed = None if getattr(args, 'bgm_random', False) else (derived_seed(args.seed, 'music') if getattr(args, 'seed', None) is not None else None)
    elif Path(choice).is_file():
        return {'path': choice, 'title': Path(choice).stem}, False
    else:
        raise FileNotFoundError(f'--bgm: not a file or folder: {choice}')
    track = bgm_tools.pick_track(folders, args.bgm_track, listing.get('listing_id'),
                                prefer=prefer, seed=seed)
    return track, fallback


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
                        help="auto|yes (seeded random clips <21s from bgm/user, else bgm/library), no, "
                             "a folder (seeded pick or --bgm-track), or an audio file; play the whole clip")
    parser.add_argument('--bgm-file', type=Path, default=None, help='Legacy alias: explicit audio file.')
    parser.add_argument('--bgm-track', default=None, help='Track name/slug substring inside the folder.')
    parser.add_argument('--bgm-start', default='auto',
                        help="Compatibility option: auto or 0 only. Music always plays in full from t=0.")
    parser.add_argument('--bgm-volume', type=float, default=0.75,
                        help='Gain after loudness normalisation (default 0.75).')
    parser.add_argument('--bgm-lufs', type=float, default=-14.0, help='Loudness target (EBU R128).')
    parser.add_argument('--beat-sync', choices=['on', 'off'], default='on',
                        help='Snap interior cuts onto phrase/bar lines (±0.40 s), keeping the full music length.')
    parser.add_argument('--beat-pulse', choices=['on', 'off'], default='off',
                        help='Off by default. Opt in for a 1–2 frame photo zoom on strong beats.')
    parser.add_argument('--listing-type', choices=['auto', 'sale', 'new', 'rent'], default='auto',
                        help='Shot order. auto: new-home flag → new, rent price / 租 → rent, else sale.')
    parser.add_argument('--seed', type=int, default=None,
                        help='Template, transition and default BGM RNG seed. Default: stable hash of the listing id.')
    parser.add_argument('--template', default='random',
                        help='Recommended: ' + ', '.join(RECOMMENDED_TEMPLATES) + ', or random. Legacy explicit names still work.')
    parser.add_argument('--variation', choices=['subtle', 'off'], default='subtle',
                        help='Controlled typography, motion and transition variation.')
    parser.add_argument('--text-bounds', choices=['off', 'warn', 'strict'], default='off',
                        help='strict exits non-zero when any text box leaves the canvas or the 60px safe area.')
    parser.add_argument('--sfx', choices=['on', 'off'], default='on',
                        help='Mix a matching transition sound under the BGM.')
    parser.add_argument('--sfx-volume', type=float, default=sfx_tools.DEFAULT_VOLUME,
                        help='Linear gain of transition SFX (default 0.12, below the music).')
    parser.add_argument('--cta', default='')
    parser.add_argument('--font', default='random',
                        help='Font style profile (dengxian, heiti, yahei, kaiti, fangsong, songti, youyuan, lishu), path, or random (default gacha).')
    parser.add_argument('--target-size-mb', type=float, default=6,
                        help='Decimal-MB budget used as the VBV maxrate cap (0 = uncapped CRF).')
    parser.add_argument('--crf', type=float, default=21, help='x264 CRF quality target (lower = better).')
    parser.add_argument('--preset', default='veryfast', help='x264 preset (ultrafast, veryfast, faster, fast, medium).')
    parser.add_argument('--threads', type=int, default=0, help='FFmpeg encoder thread count (0 = auto-detect all CPU cores).')
    parser.add_argument('--workers', type=int, default=0, help='Parallel frame generator workers (0 = auto-detect CPU cores).')
    parser.add_argument('--bgm-random', action='store_true', help='Force random BGM draw even if --seed is fixed.')
    parser.add_argument('--kenburns', choices=['on', 'off'], default='on',
                        help='Slow camera move on single photos / collage lead tile.')
    parser.add_argument('--kb-strength', type=float, default=0.08,
                        help='Ken Burns zoom amount (0.08 = 1.00->1.08).')
    parser.add_argument('--transitions', default='random',
                        help="random (default, seeded, no immediate repeat, no shake), auto (v6 rotation), "
                             "or a comma list. Names: " + ','.join(sorted(TRANSITIONS)))
    parser.add_argument('--transition-duration', type=float, default=0.40,
                        help='Cap in seconds. Random effects stay in 0.32–0.40s and are never hard cuts.')
    parser.add_argument('--diagnostics', action='store_true', help='Opt in to bounds/transition audits, preview PNGs and detailed timeline JSON.')
    parser.add_argument('--list-templates', action='store_true', help='Show the five recommended templates and exit.')
    args = parser.parse_args()
    if args.list_templates:
        print('Recommended: ' + ', '.join(RECOMMENDED_TEMPLATES))
        return
    if args.diagnostics and args.text_bounds == 'off':
        args.text_bounds = 'warn'
    args.explicit_seed = args.seed is not None
    if min(args.width, args.height, args.fps) <= 0 or args.width % 2 or args.height % 2:
        parser.error('Dimensions must be positive even numbers; fps must be positive.')
    if args.bgm_start != 'auto':
        try:
            if float(args.bgm_start) != 0.0:
                raise ValueError
        except ValueError:
            parser.error('--bgm-start must be auto or 0: the complete music clip is preserved.')
    for name in ('bgm_volume', 'sfx_volume'):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) < 0:
            parser.error('--' + name.replace('_', '-') + ' must be finite and non-negative.')
    try:
        listing, manifest = resolve_inputs(args)
        font_prof = resolve_font_profile(args.font, seed=args.seed)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Font: {font_prof['name']} ({Path(font_prof['title_path']).name})", flush=True)
    # Decode the chosen clip in full before planning pictures. Keep temporary
    # audio beside the output so it also works in restricted Windows sessions.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    audio_temp = tempfile.TemporaryDirectory(prefix='beike-render-', dir=args.output.parent)
    try:
        encoded = Path(audio_temp.name) / 'video.mp4'
        bgm_info, bgm_wav = None, None
        try:
            track, fallback = select_bgm(args, listing)
            if track:
                bgm_wav = Path(audio_temp.name) / 'bgm.wav'
                stats = bgm_tools.prepare_track(track['path'], bgm_wav,
                                                lufs=args.bgm_lufs, gain=args.bgm_volume)
                print(f"[BGM 抽卡] 随机抽中音乐: 《{track['title']}》 (时长: {stats['duration']:.2f}s | 视频画面自适应对齐该时长)", flush=True)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            parser.error(f'Cannot prepare BGM: {exc}')
        try:
            magazine = Magazine(listing, load_assets(manifest, args.media_dir), args.font, args.cta,
                                kenburns=args.kenburns == 'on', kb_strength=args.kb_strength,
                                transitions=args.transitions, transition_dur=args.transition_duration,
                                listing_type=args.listing_type, seed=args.seed,
                                beat_pulse=args.beat_pulse == 'on', fps=args.fps,
                                template=args.template, variation=args.variation, font_profile=font_prof)
        except ValueError as exc:
            parser.error(str(exc))
        if magazine.duration <= 0:
            parser.error('No sections to render.')
        got = slot_sequence(magazine.shots)
        want = [s for s in magazine.shot_order()
                if any(sh.get('slot') == s for sh in magazine.shots)]
        if got != want:
            parser.error(f'Shot order {got} does not match the {magazine.listing_type} table {want}')
        if (magazine.groups.get('community') and magazine.shot_order()[0] == 'community'
                and (not magazine.shots or magazine.shots[0].get('slot') != 'community'
                     or not magazine.shots[0].get('hero'))):
            parser.error('Opening shot must be the cover-styled 小区展示 page (title + price).')
        # The whole clip is the master clock. Analysis supplies cut targets only;
        # it never selects a window, seeks, fades, stretches or loops the music.
        if track is None:
            guard_reel_duration(magazine.duration, parser, '; insufficient or excessive material')
        else:
            try:
                seg = bgm_tools.analyze_clip_cached(track['path']) if (
                    args.beat_sync == 'on' or args.beat_pulse == 'on') else {}
                magazine.strong_beats = list(seg.get('strong_beats') or [])
                magazine.downbeats = list(seg.get('downbeats') or [])
                magazine.phrase_onsets = list(seg.get('phrase_onsets') or [])
                magazine.beat_times = list(seg.get('beats') or [])
                magazine.beat_pulse = args.beat_pulse == 'on' and bool(magazine.strong_beats)
                magazine.fit_to_music(stats['duration'],
                                      magazine.downbeats if args.beat_sync == 'on' else [],
                                      magazine.phrase_onsets if args.beat_sync == 'on' else [])
            except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                parser.error(f'Cannot fit pictures to music: {exc}')
            bgm_info = {k: track.get(k) for k in ('title', 'artist', 'slug', 'path', 'source_page', 'license')}
            bgm_info.update(user_library_fallback=fallback, start=0.0, end=magazine.duration,
                            duration=magazine.duration, full_clip=True, looped=False,
                            added_fades=False, timing_mode='music',
                            tempo=seg.get('tempo'), engine=seg.get('engine'), cache=seg.get('cache'),
                            source_lufs=stats['input_lufs'], target_lufs=args.bgm_lufs,
                            beat_sync=args.beat_sync == 'on' and bool(magazine.downbeats),
                            phrase_offset=0.0, phrase_onsets=magazine.phrase_onsets,
                            snap_window=0.40, volume=args.bgm_volume)
            print(f"BGM: {bgm_info['title']} — full clip, 0–{magazine.duration:.3f}s; "
                  f"pictures retimed, no music trimming or looping", flush=True)

        bounds = None
        if args.text_bounds != 'off':
            bounds = magazine.audit_text_bounds()
            print(f"Text bounds: {bounds['status']}, {len(bounds['violations'])} warnings", flush=True)
            if bounds['violations'] and args.text_bounds == 'strict':
                parser.error('Text bounds check failed; use --diagnostics for details.')
        # Pixel-difference proofs are opt-in diagnostics. They never rewrite chosen transitions.
        sfx_info = None
        if args.sfx == 'on':
            events = [{'time': cut['time'], 'id': cut['sfx'], 'transition': cut['type'],
                       'dir': cut.get('dir')}
                      for cut in magazine.cuts if cut.get('sfx') and cut.get('dur', 0) > 0]
            if events:
                if bgm_wav is None:
                    bgm_wav = Path(audio_temp.name) / 'bgm.wav'
                    sfx_tools.write_silence(bgm_wav, magazine.duration)
                mixed = Path(audio_temp.name) / 'mix.wav'
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

        if args.diagnostics:
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
            # Full music clip, loudness-normalised with its original start and end.
            cmd += ['-i', str(bgm_wav), '-map', '0:v:0', '-map', '1:a:0', '-c:a', 'aac', '-b:a', '128k']
        else:
            cmd += ['-an']
        # Both inputs end naturally. Avoid a global -t / -shortest on music renders:
        # even sub-frame rounding must not discard the tail of the original clip.
        if track is None:
            cmd += ['-t', f'{magazine.duration:.3f}']
        threads_flag = str(args.threads) if hasattr(args, 'threads') else '0'
        cmd += ['-c:v', 'libx264', '-preset', args.preset, '-threads', threads_flag, '-crf', f'{args.crf:g}']
        if bitrate:
            cmd += ['-maxrate', f'{bitrate}k', '-bufsize', f'{bitrate * 2}k']
        cmd += ['-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(encoded)]
        magazine.bounds_report = bounds
        proofs = magazine.transition_proof() if args.diagnostics else []
        workers = args.workers if getattr(args, 'workers', 0) > 0 else min(8, max(2, os.cpu_count() or 4))
        print(f'Rendering {magazine.duration:.1f}s, {args.width}×{args.height}, crf {args.crf:g}, '
              f'preset {args.preset}, parallel workers={workers}', flush=True)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        frames = math.ceil(magazine.duration * args.fps)
        try:
            # Pre-warm layers for thread safety
            for s in magazine.shots:
                magazine.layers(s)

            chunk_size = workers * 4
            with ThreadPoolExecutor(max_workers=workers) as executor:
                for chunk_start in range(0, frames, chunk_size):
                    chunk_end = min(frames, chunk_start + chunk_size)
                    indices = range(chunk_start, chunk_end)
                    rendered_frames = list(executor.map(
                        lambda idx: resized(magazine.frame(idx / args.fps)).tobytes(),
                        indices
                    ))
                    for b_data in rendered_frames:
                        proc.stdin.write(b_data)
                    if chunk_start % (args.fps * 3) < chunk_size:
                        print(f'  {chunk_start / args.fps:.0f}/{magazine.duration:.0f}s', flush=True)
            proc.stdin.close()
            if proc.wait():
                raise RuntimeError('ffmpeg encoding failed')
        except BaseException:
            proc.kill()
            proc.wait()
            raise

        encoded.replace(args.output)
        if args.diagnostics:
            payload = {
                'duration': magazine.duration,
                'timing_mode': 'music' if track else 'shots',
                'width': args.width,
                'height': args.height,
                'fps': args.fps,
                'listing_type': magazine.listing_type,
                'template': magazine.template_name,
                'seed': magazine.seed,
                'variation': magazine.variant,
                'fonts': {'title': SANS_BOLD_PATH if magazine.template_name in MOBILE_LAYOUTS else magazine.serif_path,
                          'body': SANS_BOLD_PATH if magazine.template_name in MOBILE_LAYOUTS else magazine.sans_path,
                          'labels': getattr(magazine, 'editorial_body_path', magazine.sans_path)},
                'text_bounds': getattr(magazine, 'bounds_report', None),
                'order': [shot_label(s) for s in magazine.shots],
                'sections': magazine.sections,
                'shots': [{'kind': s['kind'], 'plate': s.get('plate'), 'slot': s.get('slot'),
                           'name': shot_label(s), 'label': s.get('label'), 'hero': bool(s.get('hero')),
                           'title': s.get('title'), 'tag': s.get('tag'), 'start': None, 'duration': s['dur'],
                           'dur_lo': s.get('dur_lo'), 'dur_hi': s.get('dur_hi'),
                           'source_duration': s.get('dur_source_plan', s.get('dur_plan')),
                           'files': list(s.get('files') or []),
                           'kenburns': s.get('kb'), 'kb_strength': round(s.get('kb_strength', 0.0), 4),
                           'text_animation': s.get('text_animation'),
                           'text_events': [{k:v for k,v in event.items() if k != 'image'}
                                           for event in magazine.layers(s).get('text_events', [])],
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
            args.output.with_suffix('.timeline.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        if bgm_wav and bgm_wav.exists():
            bgm_wav.unlink()
        size_mb = args.output.stat().st_size / 1_000_000
        print(f'Done: {args.output} ({size_mb:.2f} MB, {magazine.duration:.1f}s)', flush=True)
    finally:
        audio_temp.cleanup()


if __name__ == '__main__':
    main()
