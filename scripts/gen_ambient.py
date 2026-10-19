"""
Instagram Reels için telifsiz fon müziği üretir (igmusic/*.mp3).

Müzik tamamen burada sentezlenir (yumuşak pad akorları + çan arpejleri),
bu yüzden telif sorunu yoktur. Bir kez çalıştırılıp çıktılar repoya
eklenir:  python scripts/gen_ambient.py
"""
import subprocess
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "igmusic"


def note(n: float) -> float:
    """MIDI nota → frekans."""
    return 440.0 * 2 ** ((n - 69) / 12)


def pad(freqs, dur, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    out = np.zeros_like(t)
    for f in freqs:
        for det in (-0.12, 0.0, 0.11):           # hafif koro etkisi
            ff = f * 2 ** (det / 12)
            out += np.sin(2 * np.pi * ff * t + np.random.rand() * 6.28)
            out += 0.25 * np.sin(2 * np.pi * 2 * ff * t)
    att, rel = min(1.5, dur / 3), min(2.0, dur / 2)
    env = np.minimum(1, t / att) * np.minimum(1, (dur - t) / rel)
    return out * env / (len(freqs) * 3)


def bell(f, dur=2.5, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    s = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * 2.01 * f * t)
         + 0.15 * np.sin(2 * np.pi * 3.0 * f * t))
    return s * np.exp(-t * 2.2) * np.minimum(1, t / 0.01)


def lowpass(x, k=24):
    return np.convolve(x, np.ones(k) / k, mode="same")


def echo(x, delay=0.38, fb=0.35, n=4, sr=SR):
    out = x.copy()
    d = int(delay * sr)
    for i in range(1, n + 1):
        out[d * i:] += x[:-d * i] * fb ** i
    return out


def track(root: int, prog, bpm: float, seconds: float, seed: int):
    np.random.seed(seed)
    beat = 60 / bpm
    bar = beat * 4
    total = int(seconds * SR)
    mix = np.zeros(total + SR * 12)
    scale = [0, 2, 4, 7, 9, 12, 14, 16]          # pentatonik
    i, t0 = 0, 0.0
    while t0 < seconds:
        chord = prog[i % len(prog)]
        freqs = [note(root + c) for c in chord] + [note(root + chord[0] - 12)]
        p = pad(freqs, bar * 2 + 1.5)
        s = int(t0 * SR)
        seg = lowpass(p)[:len(mix) - s] * 0.55
        mix[s:s + len(seg)] += seg
        for b in range(8):                        # seyrek çan arpejleri
            if np.random.rand() < 0.55:
                f = note(root + 12 + scale[np.random.randint(len(scale))])
                bb = bell(f) * 0.16
                bs = int((t0 + b * beat) * SR)
                bb = bb[:max(0, len(mix) - bs)]
                mix[bs:bs + len(bb)] += bb
        t0 += bar * 2
        i += 1
    mix = echo(mix[:total])
    mix += np.random.randn(total) * 0.002         # hafif hava
    fade = int(3 * SR)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-fade:] *= np.linspace(1, 0, fade)
    mix /= np.max(np.abs(mix)) + 1e-9
    stereo = np.stack([mix, np.roll(mix, int(0.012 * SR))], axis=1) * 0.6
    return (stereo * 32767).astype(np.int16)


def save_mp3(data, path):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    p = subprocess.run([ff, "-y", "-loglevel", "error", "-f", "s16le",
                        "-ar", str(SR), "-ac", "2", "-i", "-",
                        "-b:a", "128k", str(path)], input=data.tobytes())
    p.check_returncode()


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    tracks = {
        "huzur_cmaj": (60, [[0, 4, 7, 11], [9, 12, 16, 19], [5, 9, 12, 16],
                            [7, 11, 14, 17]], 64, 1),
        "bolluk_dmaj": (62, [[0, 4, 7, 11], [5, 9, 12, 16], [9, 12, 16, 19],
                             [7, 11, 14, 18]], 70, 2),
        "gece_amin": (57, [[0, 3, 7, 10], [5, 8, 12, 15], [3, 7, 10, 14],
                           [-2, 2, 5, 9]], 60, 3),
    }
    for name, (root, prog, bpm, seed) in tracks.items():
        save_mp3(track(root, prog, bpm, 60, seed), OUT / f"{name}.mp3")
        print("✓", name)
