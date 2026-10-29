"""BGM helpers: track lookup, full-clip preparation and deterministic beat analysis.

The slideshow uses prepare_track to retain the entire selected high-energy
clip, with loudness/volume processing only. Legacy window selection and cutting
helpers below remain available to standalone callers.

Climax detection
----------------
Decode to mono 22.05 kHz with ffmpeg, then (librosa when available, numpy fallback):
  * beat tracking -> tempo + beat times; bar phase = the beat offset (mod 4) with the
    strongest onsets, so candidate starts sit on bar lines (downbeats)
  * per-frame RMS (loudness) and onset strength (rhythmic drive), both normalised
  * every bar-aligned window of the video's length is scored:
        0.45 * mean RMS            (overall energy)
      + 0.20 * 10th-pct RMS        (sustained: no breakdown dips inside)
      + 0.20 * mean onset          (beat drive / hook density)
      + 0.15 * entry contrast      (energy jump vs. the 4 s before: a chorus "drop")
      + 0.05 * intro prior         (ramps 0->1 over the first 15% of the track)
    Windows must end >= 1 s before the track ends (no natural outro / tail).
  The best window wins; its percentile among all windows is reported as energy rank.

Cutting
-------
ffmpeg two-pass loudnorm (EBU R128, default -14 LUFS, -1.5 dBTP, linear gain) on the
segment, then a 0.3 s fade-in and 1.5 s fade-out, written as 48 kHz stereo WAV.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import random
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

AUDIO_EXT = {'.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg', '.opus'}
MAX_TRACK_SECONDS = 21.0  # Exclusive: the candidate library contains short clips only.
SR = 22050
HOP = 512


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-') or 'track'


# ---- library ---------------------------------------------------------------
@lru_cache(maxsize=512)
def _library_duration(path, size, mtime_ns):
    # Stat fields invalidate the cache when an audio file is replaced in place.
    return probe_duration(path)


def list_tracks(folder):
    """Playable clips shorter than 21 seconds, with optional library metadata.

    Filtering never edits audio or deletes files. Explicit file playback and
    prepare_track still preserve the entire supplied clip.
    """
    folder = Path(folder)
    meta = {}
    lib = folder / 'library.json'
    if lib.is_file():
        for item in json.loads(lib.read_text(encoding='utf-8')).get('tracks', []):
            meta[item.get('file')] = item
    tracks = []
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path.suffix.lower() in AUDIO_EXT and path.is_file():
            stat = path.stat()
            try:
                duration = _library_duration(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
            except (subprocess.CalledProcessError, ValueError):
                continue  # Undecodable files are not music candidates.
            if duration >= MAX_TRACK_SECONDS:
                continue
            info = dict(meta.get(path.name, {}))
            info.setdefault('title', path.stem)
            info['path'] = str(path)
            info['slug'] = info.get('slug') or slug(path.stem)
            info['duration'] = duration
            tracks.append(info)
    return tracks


def pick_track(folders, name=None, rotate_key=None, prefer=None, seed=None):
    """Choose a track from the first folder(s) that contain audio.

    name        substring match on file name / title / slug (case-insensitive)
    rotate_key  any string (e.g. listing id): stable rotation through the library
    seed        optional RNG seed: seeded random pick instead of stable rotation
    prefer      optional slug list. When set, rotation stays inside those slugs
                if any of them are in the pool (softer default library picks).
    """
    pool = []
    for folder in folders:
        pool += list_tracks(folder)
    if not pool:
        raise FileNotFoundError(f'No playable audio shorter than {MAX_TRACK_SECONDS:g}s in '
                                + ', '.join(map(str, folders)))
    if name and name.lower() not in ('auto', 'random'):
        key = name.lower()
        hits = [t for t in pool if key in Path(t['path']).name.lower() or key in t['title'].lower()
                or key in t['slug']]
        if not hits:
            raise FileNotFoundError(f'No track matching "{name}". Available: '
                                    + ', '.join(t['slug'] for t in pool))
        return hits[0]
    if prefer:
        wanted = []
        for slug_name in prefer:
            wanted += [t for t in pool if t['slug'] == slug_name or slug_name in t['slug']]
        # Preserve prefer order, drop duplicates.
        seen, ordered = set(), []
        for track in wanted:
            if track['path'] not in seen:
                ordered.append(track)
                seen.add(track['path'])
        if ordered:
            pool = ordered
    if seed is not None:
        return random.Random(seed).choice(pool)
    # Default: true random pick across candidate audio clips
    return random.choice(pool)


# ---- analysis --------------------------------------------------------------
def probe_duration(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of',
                             'default=nw=1:nk=1', str(path)],
                            capture_output=True, text=True, check=True)
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f'Audio duration must be positive and finite: {path}')
    return duration


def decode_mono(path, sr=SR):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(sr),
                          '-f', 'f32le', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def _features(y, sr):
    try:
        import librosa
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
        onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
        tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=HOP)
        tempo = float(np.atleast_1d(tempo)[0])
        beat_times = librosa.frames_to_time(beats, sr=sr, hop_length=HOP)
        engine = 'librosa'
    except Exception:            # numpy fallback: RMS + spectral-flux onsets, no beats
        n = len(y) // HOP
        frames = y[:n * HOP].reshape(n, HOP)
        rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
        spec = np.abs(np.fft.rfft(frames * np.hanning(HOP), axis=1))
        onset = np.maximum(0, np.diff(spec, axis=0, prepend=spec[:1])).sum(axis=1)
        tempo, beat_times, engine = 0.0, np.array([]), 'numpy'
    m = min(len(rms), len(onset))
    return rms[:m], onset[:m], tempo, np.asarray(beat_times), engine


def _norm(x):
    lo, hi = np.percentile(x, 2), np.percentile(x, 98)
    return np.clip((x - lo) / (hi - lo + 1e-9), 0, 1)


def _annotate_beats(beats, drive, fps, start, length, phase):
    """Beat times relative to `start`, plus onset strength, downbeats and strong beats.

    Strong beats are the downbeats plus any beat at or above the 75th percentile
    of onset strength inside the window. Used for cut snapping and the photo pulse.
    """
    beats = list(np.asarray(beats, float))
    seg_b, seg_s, down = [], [], []
    n_drive = len(drive)
    for i, b in enumerate(beats):
        if b < start - 1e-4 or b > start + length + 1e-4:
            continue
        rel = round(float(b - start), 4)
        if n_drive:
            idx = int(np.clip(round(b * fps), 0, n_drive - 1))
            strength = round(float(drive[idx]), 4)
        else:
            strength = 0.0
        seg_b.append(rel)
        seg_s.append(strength)
        if phase is not None and (i - phase) % 4 == 0:
            down.append(rel)
    hi = float(np.percentile(seg_s, 75)) if seg_s else 1.0
    down_set = set(down)
    strong = [t for t, s in zip(seg_b, seg_s) if t in down_set or s >= hi]
    return seg_b, seg_s, down, strong


def _bar_phase(beats, drive, fps):
    if len(beats) < 8 or not len(drive):
        return None
    return max(range(4), key=lambda k: drive[np.clip((beats[k::4] * fps).astype(int), 0,
                                                     len(drive) - 1)].sum())


def find_climax(path, length, tail_guard=1.0):
    """Best bar-aligned window of `length` seconds. Returns a dict (see module doc).

    Beat lists are seconds relative to the window start:
      beats, beat_strength (parallel), downbeats, strong_beats.
    """
    y = decode_mono(path)
    total = len(y) / SR
    rms, onset, tempo, beats, engine = _features(y, SR)
    fps = SR / HOP
    loud = _norm(20 * np.log10(rms + 1e-6))
    drive = _norm(onset)
    smooth = np.convolve(loud, np.ones(int(fps)) / int(fps), mode='same')     # 1 s smoothing
    phase = _bar_phase(beats, drive, fps)
    latest = total - length - tail_guard
    if latest <= 0:
        span = min(length, total)
        seg_b, seg_s, down, strong = _annotate_beats(beats, drive, fps, 0.0, span, phase)
        return dict(start=0.0, end=round(span, 3), tempo=round(float(tempo), 1), beats=seg_b,
                    beat_strength=seg_s, downbeats=down, strong_beats=strong,
                    score=0.0, rank=1.0, candidates=1, engine=engine, total=round(total, 2),
                    looped=total < length)
    if phase is not None:
        starts = beats[phase::4]
    else:
        starts = np.arange(0, latest, 0.5)
    starts = starts[(starts >= 0) & (starts <= latest)]
    if not len(starts):
        starts = np.array([0.0])
    scores = []
    for s in starts:
        a, b = int(s * fps), int((s + length) * fps)
        # Entry contrast needs a real "before": windows in the first 4 s get none.
        pre = smooth[a - int(4 * fps):a] if a >= int(4 * fps) else None
        entry = 0.0 if pre is None else max(0.0, smooth[a:a + int(4 * fps)].mean() - pre.mean())
        # Mild intro prior: a chorus rarely starts in the first ~15% of a song.
        prior = min(1.0, s / (0.15 * total))
        scores.append(0.45 * loud[a:b].mean() + 0.20 * np.percentile(smooth[a:b], 10)
                      + 0.20 * drive[a:b].mean() + 0.15 * entry + 0.05 * prior)
    scores = np.array(scores)
    best = int(scores.argmax())
    start = float(starts[best])
    rank = float((scores <= scores[best]).mean())
    seg_b, seg_s, down, strong = _annotate_beats(beats, drive, fps, start, length, phase)
    return dict(start=round(start, 3), end=round(start + length, 3), tempo=round(float(tempo), 1),
                beats=seg_b, beat_strength=seg_s, downbeats=down, strong_beats=strong,
                score=round(float(scores[best]), 4), rank=round(rank, 3),
                candidates=int(len(starts)), engine=engine, total=round(total, 2), looped=False,
                energy_pct_of_track=round(float(loud[int(start * fps):int((start + length) * fps)].mean()
                                                / (loud.mean() + 1e-9)), 3))


def find_phrase(path, length=17.6, headroom=2.6, tail_guard=1.0):
    """Softer melodic-phrase window, not a chorus drop.

    The window starts on a downbeat where mid-band (melodic) energy rises and
    holds. Scoring penalises hot peaks, wide dynamic swings and onset density,
    so an EDM drop loses to a sustained phrase. Beat lists are seconds relative
    to that onset and cover `length + headroom` when the track allows it, so a
    slightly longer or shorter edit can keep the same phrase start.

    Extra keys vs find_climax: phrase_onsets, mood, reason, phrase_rise,
    phrase_sustain, bar_index, analyzed_length.
    """
    y = decode_mono(path)
    total = len(y) / SR
    _rms, onset, tempo, beats, engine = _features(y, SR)
    fps = SR / HOP
    drive = _norm(onset)
    phase = _bar_phase(beats, drive, fps)
    n = len(y) // HOP
    frames = y[:n * HOP].reshape(n, HOP) * np.hanning(HOP)
    spec = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(HOP, 1.0 / SR)
    mid = spec[:, (freqs >= 250) & (freqs <= 3200)].mean(axis=1)
    bass = spec[:, (freqs >= 40) & (freqs <= 140)].mean(axis=1)
    win = max(1, int(round(0.40 * fps)))
    kernel = np.ones(win) / win
    sm = np.convolve(mid, kernel, mode='same')
    sb = np.convolve(bass, kernel, mode='same')
    mlen = min(len(sm), len(sb), len(drive))
    sm, sb, drive = sm[:mlen], sb[:mlen], drive[:mlen]

    def pack(start, meta, score, candidates):
        span = min(max(0.0, total - start), float(length) + float(headroom))
        phrase_abs = [start]
        for item in meta.get('later') or []:
            if start + 0.05 < item <= start + span + 1e-3:
                phrase_abs.append(item)
        phrase_rel = {round(t - start, 4) for t in phrase_abs if -1e-3 <= t - start <= span + 1e-3}
        # Two-bar grid from the window onset: a melodic phrase is longer than one bar.
        # Single bars stay in `downbeats` as the secondary snap target.
        seg_b, seg_s, down, strong = _annotate_beats(beats, drive, fps, start, span, phase)
        for i, bar in enumerate(down):
            if i % 2 == 0:
                phrase_rel.add(round(float(bar), 4))
        phrase_rel = sorted(phrase_rel)
        reason = (
            f"soft melodic phrase at {start:.3f}s (bar {meta.get('bar_index', 0)}, "
            f"mid-band rise {meta.get('rise', 0):.3f}, sustain {meta.get('sustain', 0):.2f}, "
            f"swing {meta.get('swing', 0):.3f}, hot-peak fraction {meta.get('hot', 0):.3f}). "
            f"Chorus-drop windows were penalised. Snap targets are phrase onsets and bar "
            f"lines, not kicks."
        )
        return dict(start=round(float(start), 3), end=round(float(start) + float(length), 3),
                    tempo=round(float(tempo), 1), beats=seg_b, beat_strength=seg_s,
                    downbeats=down, strong_beats=strong, phrase_onsets=phrase_rel,
                    score=round(float(score), 4), rank=None, candidates=int(candidates),
                    engine=engine, total=round(total, 2), looped=False, mood='soft-phrase',
                    reason=reason, phrase_rise=round(float(meta.get('rise', 0)), 4),
                    phrase_sustain=round(float(meta.get('sustain', 0)), 4),
                    bar_index=int(meta.get('bar_index', 0)), analyzed_length=round(span, 3))

    if phase is None or len(beats) < 8 or mlen < 8:
        return pack(0.0, dict(rise=0, sustain=0, bar_index=0, swing=0, hot=0, later=[]), 0.0, 0)

    downs = np.asarray(beats[phase::4], float)
    rows = []
    for i, d in enumerate(downs):
        idx = int(np.clip(round(float(d) * fps), 0, len(sm) - 1))
        pre = sm[max(0, idx - int(0.75 * fps)):idx]
        post = sm[idx:idx + int(1.05 * fps)]
        if len(pre) < 3 or len(post) < 3:
            continue
        rise = float(post.mean() - pre.mean())
        sustain = float(np.min(post) / (np.mean(post) + 1e-9))
        rows.append((i, float(d), rise, sustain))
    if not rows:
        return pack(0.0, dict(rise=0, sustain=0, bar_index=0, swing=0, hot=0, later=[]), 0.0, 0)
    rises = np.array([r[2] for r in rows])
    thr = float(np.percentile(rises, 72))
    phrases = [r for r in rows if r[2] >= max(thr, 0.02) and r[3] >= 0.75]
    if not phrases:
        phrases = [r for r in rows if r[2] >= 0 and r[3] >= 0.70] or rows
    score_len = min(float(length), max(8.0, total - tail_guard - 1.0))
    latest = total - score_len - tail_guard
    peak_thr = float(np.percentile(sm, 92))
    best = None
    for i, d, rise, sus in phrases:
        if d < 6.0 or d > latest:
            continue
        a = int(d * fps)
        b = min(len(sm), int((d + score_len) * fps))
        if b - a < int(4 * fps):
            continue
        seg = sm[a:b]
        hot = float((seg >= peak_thr).mean())
        swing = float(np.percentile(seg, 90) - np.percentile(seg, 20))
        onset_m = float(drive[a:b].mean())
        bass_m = float(sb[a:b].mean())
        level = float(np.percentile(seg, 40))
        score = (0.55 * level - 0.35 * swing - 1.4 * hot - 0.50 * onset_m
                 - 0.02 * bass_m + 0.25 * min(rise, 0.8)
                 + 0.05 * min(1.0, d / (0.18 * total + 1e-9)))
        if best is None or score > best[0]:
            best = (score, d, i, rise, sus, level, swing, hot)
    later = [r[1] for r in phrases]
    if best is None:
        start = float(rows[min(3, len(rows) - 1)][1])
        meta = dict(rise=0.0, sustain=0.0, bar_index=0, swing=0.0, hot=0.0, later=later)
        return pack(start, meta, 0.0, len(phrases))
    meta = dict(rise=best[3], sustain=best[4], bar_index=best[2], level=best[5],
                swing=best[6], hot=best[7], later=later)
    return pack(float(best[1]), meta, best[0], len(phrases))


# ---- cutting ---------------------------------------------------------------
def _normalise_audio(inputs, out, lufs, gain, fades=()):
    """Shared two-pass loudness processing; inputs determine any legacy trimming."""
    target = f'I={lufs}:TP=-1.5:LRA=11'
    first = subprocess.run(['ffmpeg', '-hide_banner', '-nostats'] + inputs +
                           ['-af', f'loudnorm={target}:print_format=json', '-f', 'null', '-'],
                           capture_output=True, text=True, check=True)
    m = json.loads(first.stderr[first.stderr.rfind('{'):first.stderr.rfind('}') + 1])
    norm = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
            f"offset={m['target_offset']}:linear=true")
    chain = [norm, 'aresample=48000']
    if gain != 1.0:
        chain.append(f'volume={gain}')
    chain += list(fades)
    subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y'] + inputs +
                   ['-af', ','.join(chain), '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', str(out)],
                   check=True)
    return dict(input_lufs=float(m['input_i']), target_lufs=lufs)


def prepare_track(path, out, lufs=-14.0, gain=0.75):
    """Decode the ENTIRE clip to a mixable WAV. No seeking, trimming, looping or fades.

    Probe the resulting PCM duration rather than MP3 container padding so the
    picture timeline matches the audio samples actually played.
    """
    stats = _normalise_audio(['-i', str(path)], out, lufs, gain)
    stats['duration'] = probe_duration(out)
    return stats


def cut_segment(path, start, length, out, lufs=-14.0, fade_in=0.3, fade_out=1.5, gain=1.0, loop=False):
    """Legacy segment helper; the slideshow uses prepare_track to keep clips whole."""
    src = ['-stream_loop', '-1'] if loop else []
    inputs = src + ['-ss', f'{start:.3f}', '-t', f'{length:.3f}', '-i', str(path)]
    fades = [f'afade=t=in:st=0:d={fade_in}',
             f'afade=t=out:st={max(0.0, length - fade_out):.3f}:d={fade_out}']
    return _normalise_audio(inputs, out, lufs, gain, fades)


def measure_lufs(path):
    res = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-af',
                          'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True).stderr
    i = re.findall(r'I:\s+(-?[\d.]+) LUFS', res)
    p = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', res)
    return dict(integrated=float(i[-1]) if i else None, true_peak=float(p[-1]) if p else None)


if __name__ == '__main__':      # quick CLI: python3 bgm_tools.py track.mp3 22.5
    import sys
    info = find_climax(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 22.5)
    info['beat_count'] = len(info.get('beats') or [])
    info['downbeat_count'] = len(info.get('downbeats') or [])
    info['strong_count'] = len(info.get('strong_beats') or [])
    for key in ('beats', 'beat_strength', 'downbeats', 'strong_beats'):
        info.pop(key, None)
    print(json.dumps(info, ensure_ascii=False, indent=1))


# ---- deterministic analysis cache -----------------------------------------------
ANALYSIS_VERSION = 1


def analyze_clip_cached(path):
    """Beat annotations for an already curated high-energy clip, always from t=0.

    Uses its own cache file, preserving the existing phrase-analysis caches.
    No window selection or music edits are performed.
    """
    path = Path(path)
    st = path.stat()
    key = dict(v=ANALYSIS_VERSION, size=st.st_size, mtime_ns=st.st_mtime_ns)
    cache = path.parent / '.analysis' / f'{path.stem}.clip.json'
    try:
        data = json.loads(cache.read_text(encoding='utf-8'))
        if data.get('key') == key:
            return dict(data['result'], cache='hit')
    except (OSError, ValueError, KeyError):
        pass
    y = decode_mono(path)
    _rms, onset, tempo, beats, engine = _features(y, SR)
    drive = _norm(onset)
    fps = SR / HOP
    phase = _bar_phase(beats, drive, fps)
    seg_b, seg_s, down, strong = _annotate_beats(beats, drive, fps, 0, len(y) / SR, phase)
    result = dict(beats=seg_b, beat_strength=seg_s, downbeats=down,
                  strong_beats=strong, phrase_onsets=down[::2], tempo=tempo, engine=engine)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(dict(key=key, result=result)), encoding='utf-8')
    except OSError:
        pass
    return dict(result, cache='miss')


def find_phrase_cached(path, length=17.6, headroom=2.6, tail_guard=1.0):
    """find_phrase with a per-track JSON cache in <track folder>/.analysis/<stem>.json.

    Key = file size + mtime + params + ANALYSIS_VERSION, so edits or a new analysis
    version recompute automatically. Pure numpy/librosa, deterministic.
    """
    path = Path(path)
    st = path.stat()
    key = dict(v=ANALYSIS_VERSION, size=st.st_size, mtime=int(st.st_mtime),
               length=length, headroom=headroom, tail_guard=tail_guard)
    cache = path.parent / '.analysis' / f'{path.stem}.json'
    try:
        data = json.loads(cache.read_text())
        if data.get('key') == key:
            seg = data['result']
            seg['cache'] = 'hit'
            return seg
    except Exception:
        pass
    seg = find_phrase(str(path), length, headroom=headroom, tail_guard=tail_guard)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({'key': key, 'result': seg}, ensure_ascii=False, default=float))
    except OSError:
        pass
    seg['cache'] = 'miss'
    return seg
