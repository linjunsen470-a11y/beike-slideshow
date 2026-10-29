"""Procedural transition sound effects.

Synthesized with numpy (filtered noise sweeps, sine pitch drops, impulses) and
written as 48 kHz stereo WAV. These are project-original waveforms: no
third-party samples and no third-party license. See sfx/library.json.
"""
from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np

SR = 48000
DEFAULT_VOLUME = 0.12
SFX_DIR = Path(__file__).resolve().parent / 'sfx'

# Transition name -> effect id. Unknown names fall through to whoosh except hard cuts.
SFX_FOR = {
    'whip': 'whoosh',
    'push': 'whoosh',
    'spin': 'whoosh',
    'slide_left': 'whoosh',
    'slide_right': 'whoosh',
    'slide_up': 'whoosh',
    'wipe': 'whoosh',
    'zoom': 'whoosh',
    'fade': 'whoosh',
    'black': 'whoosh',
    'zoom_blur': 'impact',
    'shake': 'impact',
    'flash': 'shutter',
    'glitch': 'glitch',
    'light_leak': 'shimmer',
    'cut': None,
}

_USED_FOR = {}
for _kind, _sfx in SFX_FOR.items():
    if _sfx:
        _USED_FOR.setdefault(_sfx, []).append(_kind)


def sfx_for(kind):
    return SFX_FOR.get(kind)


def _lowpass_sweep(noise, sr, f0, f1, q=0.7):
    """Time-varying RBJ lowpass. Coefficients refresh every 32 samples."""
    n = len(noise)
    y = np.empty(n, np.float64)
    z1 = z2 = 0.0
    step = 32
    i = 0
    while i < n:
        t = i / max(1, n - 1)
        freq = min(f0 * ((f1 / f0) ** t), sr * 0.45)
        w0 = 2 * math.pi * freq / sr
        alpha = math.sin(w0) / (2 * q)
        cosw = math.cos(w0)
        b0 = (1 - cosw) / 2
        b1 = 1 - cosw
        b2 = (1 - cosw) / 2
        a0 = 1 + alpha
        a1 = -2 * cosw / a0
        a2 = (1 - alpha) / a0
        b0, b1, b2 = b0 / a0, b1 / a0, b2 / a0
        end = min(n, i + step)
        for j in range(i, end):
            inp = float(noise[j])
            out = b0 * inp + z1
            if abs(out) > 8.0:
                out = math.copysign(8.0, out)
                z1 = z2 = 0.0
            else:
                z1 = b1 * inp - a1 * out + z2
                z2 = b2 * inp - a2 * out
            y[j] = out
        i = end
    return y


def _edge_fade(y, sr, fade_ms):
    n = int(sr * fade_ms / 1000)
    if n < 2 or len(y) < 2 * n:
        return y
    ramp = np.linspace(0.0, 1.0, n)
    y = y.copy()
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def _finish(y, sr, gain=0.89, fade_ms=4):
    y = np.asarray(y, np.float64)
    y -= y.mean()
    y = _edge_fade(y, sr, fade_ms)
    peak = float(np.max(np.abs(y))) + 1e-9
    if not math.isfinite(peak) or peak > 1e6:
        raise RuntimeError('SFX synthesis diverged')
    return (y / peak * gain).astype(np.float32)


def _stereo(mono, sr, width=0.35):
    """Tiny Haas delay for width. mono is float32."""
    delay = max(1, int(sr * 0.0004))
    right = np.concatenate([np.zeros(delay, np.float32), mono])[:len(mono)]
    left = mono
    mid = (left + right) * 0.5
    side = (left - right) * 0.5 * width
    stereo = np.stack([mid + side, mid - side], axis=1)
    peak = float(np.max(np.abs(stereo))) + 1e-9
    return stereo / peak * float(np.max(np.abs(mono)))


def synth_whoosh(sr=SR):
    dur = 0.46
    n = int(sr * dur)
    rng = np.random.RandomState(7)
    noise = rng.standard_normal(n)
    high = _lowpass_sweep(noise, sr, 380, 5400, q=0.85)
    low = _lowpass_sweep(noise, sr, 140, 480, q=0.6)
    t = np.arange(n) / sr
    env = np.sin(np.pi * t / dur) ** 1.15
    y = (high - 0.9 * low) * env
    freq = 480 * (3.4 ** (t / dur))
    phase = np.cumsum(freq) / sr * 2 * np.pi
    y += 0.16 * np.sin(phase) * env
    return _finish(y, sr, gain=0.88, fade_ms=5)


def synth_impact(sr=SR):
    """Pitch-drop body + a bright click so the hit reads on phone speakers."""
    dur = 0.40
    n = int(sr * dur)
    t = np.arange(n) / sr
    rng = np.random.RandomState(11)
    f = 120 + 220 * np.exp(-t * 16)
    phase = np.cumsum(f) / sr * 2 * np.pi
    body = np.sin(phase) * np.exp(-t * 6.0)
    f2 = 480 * np.exp(-t * 20) + 180
    phase2 = np.cumsum(f2) / sr * 2 * np.pi
    mid = np.sin(phase2) * np.exp(-t * 11)
    click = rng.standard_normal(n) * np.exp(-((t - 0.010) ** 2) / (2 * 0.0016 ** 2))
    y = 0.50 * body + 0.75 * mid + 0.90 * click
    return _finish(y, sr, gain=0.90, fade_ms=2)


def synth_shutter(sr=SR):
    dur = 0.26
    n = int(sr * dur)
    t = np.arange(n) / sr
    rng = np.random.RandomState(13)
    noise = rng.standard_normal(n)

    def click_at(tc, amp, width):
        return amp * noise * np.exp(-((t - tc) ** 2) / (2 * width ** 2))

    y = click_at(0.010, 1.0, 0.0011) + click_at(0.052, 0.42, 0.0009)
    y = np.diff(y, prepend=y[:1])          # brighten: shutter, not a thump
    return _finish(y, sr, gain=0.72, fade_ms=1)


def synth_glitch(sr=SR):
    dur = 0.34
    n = int(sr * dur)
    t = np.arange(n) / sr
    rng = np.random.RandomState(17)
    noise = rng.standard_normal(n)
    gate = (np.sin(2 * np.pi * 22 * t) > 0.05).astype(np.float64)
    ticks = (np.sin(2 * np.pi * 90 * t) > 0.93).astype(np.float64)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 0.75
    y = noise * (0.55 * gate + 1.1 * ticks) * env
    y = np.round(y * 8) / 8
    buzz_f = 980 - 620 * t / dur
    y += 0.12 * np.sign(np.sin(2 * np.pi * buzz_f * t)) * np.exp(-t * 5) * env
    return _finish(y, sr, gain=0.78, fade_ms=2)


def synth_shimmer(sr=SR):
    dur = 0.50
    n = int(sr * dur)
    t = np.arange(n) / sr
    rng = np.random.RandomState(19)
    y = np.zeros(n)
    for i, freq in enumerate((1680, 2240, 2960, 3920, 4960)):
        y += (0.24 / (1 + i * 0.32)) * np.sin(2 * np.pi * freq * t + i * 0.6)
    env = np.sin(np.pi * t / dur) ** 0.85
    air = _lowpass_sweep(rng.standard_normal(n), sr, 1800, 7200, q=0.55)
    y = y * env + 0.22 * air * env
    return _finish(y, sr, gain=0.70, fade_ms=8)


SYNTH = {
    'whoosh': synth_whoosh,
    'impact': synth_impact,
    'shutter': synth_shutter,
    'glitch': synth_glitch,
    'shimmer': synth_shimmer,
}

DESCR = {
    'whoosh': 'Filtered-noise band sweep with a soft rising tone. Peak at the centre of the file.',
    'impact': 'Sine pitch drop plus a short bright click. Peak is the click, aligned to the cut.',
    'shutter': 'Two high-passed noise clicks (shutter). The louder click is the peak.',
    'glitch': 'Gated, bit-crushed noise with a descending buzz.',
    'shimmer': 'High sine partials plus airy noise. Peak at the centre of the swell.',
}


def write_wav(path, stereo, sr=SR):
    pcm = np.clip(np.asarray(stereo, np.float32), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype('<i2')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'w') as handle:
        handle.setnchannels(pcm.shape[1] if pcm.ndim == 2 else 1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())


def read_wav(path):
    with wave.open(str(path), 'rb') as handle:
        sr = handle.getframerate()
        ch = handle.getnchannels()
        frames = handle.readframes(handle.getnframes())
    data = np.frombuffer(frames, np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch)
    else:
        data = data.reshape(-1, 1)
    return data, sr


def write_silence(path, seconds, sr=SR):
    n = max(1, int(round(seconds * sr)))
    write_wav(path, np.zeros((n, 2), np.float32), sr)


def _limit(x, thresh=0.89, ceil=0.98):
    """Leave samples under thresh untouched. Soft-compress only the overs."""
    ax = np.abs(x)
    over = ax > thresh
    if not np.any(over):
        return x, False
    extra = ax[over] - thresh
    comp = (ceil - thresh) * (1 - np.exp(-extra / (ceil - thresh)))
    y = np.array(x, copy=True)
    y[over] = np.sign(x[over]) * (thresh + comp)
    return y, True


def ensure_library(folder=None, force=False):
    """Write wavs + library.json. Returns {id: meta}."""
    folder = Path(folder or SFX_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    lib_path = folder / 'library.json'
    if lib_path.is_file() and not force and all((folder / f'{name}.wav').is_file() for name in SYNTH):
        meta = json.loads(lib_path.read_text())
        return {item['id']: item for item in meta['sounds']}, folder
    sounds = []
    for name, fn in SYNTH.items():
        mono = fn(SR)
        peak_sec = round(float(np.argmax(np.abs(mono)) / SR), 4)
        stereo = _stereo(mono, SR)
        write_wav(folder / f'{name}.wav', stereo, SR)
        sounds.append({
            'id': name,
            'file': f'{name}.wav',
            'duration_sec': round(len(mono) / SR, 4),
            'peak_sec': peak_sec,
            'sample_rate': SR,
            'channels': 2,
            'used_for': _USED_FOR.get(name, []),
            'description': DESCR[name],
            'origin': 'procedural-original',
            'license': None,
        })
    payload = {
        'note': (
            'Original sound effects synthesized procedurally by sfx_tools.py '
            '(numpy: filtered noise sweeps, sine pitch drops, gated noise, impulses). '
            'No third-party samples were used. license is null on purpose: these files '
            'are project-original synthesis and are not under a third-party license.'
        ),
        'origin': 'procedural-original',
        'license': None,
        'sample_rate': SR,
        'sounds': sounds,
    }
    lib_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    return {item['id']: item for item in sounds}, folder


def mix_under(bed_wav, events, out_wav, volume=DEFAULT_VOLUME, folder=None):
    """Add SFX onto a stereo bed. Each event's peak sample lands on event['time'].

    events: [{time, id, transition, dir}]
    Returns a small report dict.
    """
    index, folder = ensure_library(folder)
    bed, sr = read_wav(bed_wav)
    if sr != SR:
        raise RuntimeError(f'SFX mix expects {SR} Hz, got {sr}')
    if bed.shape[1] == 1:
        bed = np.repeat(bed, 2, axis=1)
    mix = bed.astype(np.float32)
    added = np.zeros_like(mix)
    placed = []
    cache = {}
    for event in events:
        name = event.get('id')
        if not name or name not in index:
            continue
        if name not in cache:
            audio, file_sr = read_wav(folder / index[name]['file'])
            if file_sr != sr:
                raise RuntimeError(f'{name} sample rate {file_sr} != {sr}')
            cache[name] = audio
        audio = cache[name]
        peak = int(round(index[name]['peak_sec'] * sr))
        start = int(round(float(event['time']) * sr)) - peak
        src_i = 0
        dst_i = start
        if dst_i < 0:
            src_i = -dst_i
            dst_i = 0
        n = min(len(audio) - src_i, len(mix) - dst_i)
        if n <= 0:
            continue
        chunk = audio[src_i:src_i + n]
        if event.get('dir') == 'left':
            chunk = chunk[:, ::-1]
        added[dst_i:dst_i + n] += chunk * float(volume)
        placed.append({
            'time': round(float(event['time']), 4),
            'id': name,
            'file': index[name]['file'],
            'transition': event.get('transition'),
            'dir': event.get('dir'),
            'peak_sec': index[name]['peak_sec'],
            'start_sec': round(float(event['time']) - index[name]['peak_sec'], 4),
        })
    mixed = mix + added
    limited, engaged = _limit(mixed)
    write_wav(out_wav, limited, sr)
    return {
        'volume': float(volume),
        'events': placed,
        'limiter': engaged,
        'peak': round(float(np.max(np.abs(limited))), 4),
        'bed_peak': round(float(np.max(np.abs(bed))), 4),
        'sfx_peak': round(float(np.max(np.abs(added))) if added.size else 0.0, 4),
    }


if __name__ == '__main__':
    index, folder = ensure_library(force=True)
    for item in index.values():
        print(f"{item['id']}: {item['duration_sec']:.3f}s peak@{item['peak_sec']:.3f}s -> {folder / item['file']}")
