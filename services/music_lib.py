"""
Fon müziği kütüphanesi (ElevenLabs Music)
─────────────────────────────────────────
Instagram yazılı Reels'lerinin (manifest, numeroloji, gök olayı…) fon
müziği. Parçalar ElevenLabs'te BİR KEZ üretilip volume'e (DATA_DIR/music)
kaydedilir ve sonra karışık sırayla tekrar tekrar kullanılır; her video
için yeniden üretilmez. İlk 6 parça elle, ikinci 6 parça ayın 1'inde
üretilir; kütüphane 12 parçaya (MUSIC_MAX_TRACKS) ulaşınca yeni üretim
durur ve parçalar döngüyle kullanılır.

Kütüphane boşsa eski sentez parçalara (igmusic/) düşülür.
"""

import os
import json
import random
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

URL = "https://api.elevenlabs.io/v1/music"
TRACK_SEC = int(os.environ.get("MUSIC_TRACK_SEC", "75"))
BATCH = 6

_BASE = ("Soft, warm, calm instrumental background music for a short "
         "astrology video. Gentle and low, no sharp or high-pitched sounds, "
         "no drums, no vocals, slow tempo. Starts right away with the full "
         "arrangement (no long intro), smooth fade out at the end. ")
PROMPTS = [
    "Warm felt piano with soft string pad, dreamy and hopeful.",
    "Deep mystical ambient pad with slow cello drones, night sky mood.",
    "Gentle harp arpeggios over a soft warm synth pad, magical and serene.",
    "Lo-fi mellow electric piano with tape warmth, cozy and peaceful.",
    "Soft acoustic guitar fingerpicking with warm ambient pad, calm sunrise.",
    "Slow cinematic strings and low piano, emotional and uplifting.",
    "Tibetan singing bowl tones blended with warm low pad, meditative.",
    "Soft music box melody muffled and warm over gentle pad, nostalgic.",
    "Warm Rhodes piano chords with subtle vinyl texture, relaxed evening.",
    "Ethereal choir-like pad without words, low and soft, cosmic calm.",
    "Gentle flute melody over warm drone, mystical desert night.",
    "Soft ambient piano with distant reverb, rain at night, introspective.",
    "Low warm marimba patterns with soft pad, light and positive.",
    "Slow orchestral swell with soft horns and strings, hopeful dawn.",
    "Warm analog synth pad with slow evolving texture, deep space calm.",
    "Gentle kalimba notes softened with warm pad, peaceful and sweet.",
    "Soft nylon guitar and cello duet, intimate and romantic.",
    "Mellow jazz piano ballad, brushed and quiet, late night calm.",
]


def music_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "music"


def _state_file() -> Path:
    return music_dir() / "library.json"


def _load() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except Exception:
        return {"used_prompts": [], "last": ""}


def _save(st: dict) -> None:
    music_dir().mkdir(parents=True, exist_ok=True)
    _state_file().write_text(json.dumps(st, ensure_ascii=False),
                             encoding="utf-8")


def tracks() -> list:
    return sorted(music_dir().glob("*.mp3")) if music_dir().exists() else []


def pick() -> str:
    """Kütüphaneden rastgele parça (bir önceki tekrar edilmez)."""
    files = tracks()
    if not files:
        return ""
    st = _load()
    choices = [f for f in files if f.name != st.get("last")] or files
    f = random.choice(choices)
    st["last"] = f.name
    _save(st)
    return str(f)


def _compose(prompt: str, dst: Path) -> None:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY tanımlı değil")
    r = requests.post(
        URL, params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json={"prompt": _BASE + prompt, "music_length_ms": TRACK_SEC * 1000,
              "model_id": os.environ.get("ELEVENLABS_MUSIC_MODEL", "music_v1"),
              "force_instrumental": True},
        timeout=900)
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.content)


def generate_batch(n: int = BATCH) -> dict:
    """Henüz kullanılmamış n prompt'la yeni parça üretir."""
    st = _load()
    todo = [p for p in PROMPTS if p not in st["used_prompts"]][:n]
    made, errors = [], []
    for p in todo:
        idx = PROMPTS.index(p) + 1
        dst = music_dir() / f"el_{idx:02d}.mp3"
        try:
            _compose(p, dst)
            st["used_prompts"].append(p)
            _save(st)
            made.append(dst.name)
            log.info(f"🎵 Müzik üretildi: {dst.name}")
        except Exception as e:
            log.warning(f"Müzik üretilemedi ({idx}): {e}")
            errors.append(str(e)[:200])
            if "401" in str(e) or "402" in str(e) or "quota" in str(e).lower():
                break
    res = {"made": made, "errors": errors, "total": len(tracks())}
    try:
        from telegram_bot import send as tg_send
        tg_send(f"🎵 Müzik kütüphanesi: {len(made)} yeni parça üretildi, "
                f"toplam {res['total']}"
                + (f"\n⚠️ {errors[0]}" if errors else ""))
    except Exception:
        pass
    return res


def monthly_job() -> None:
    """Ayda 6 parça; kütüphane MUSIC_MAX_TRACKS'e (12 = iki ay) ulaşınca
    yeni üretim durur, mevcut parçalar döngüyle kullanılır."""
    if os.environ.get("MUSIC_MONTHLY", "1") in ("0", "false"):
        return
    if len(tracks()) >= int(os.environ.get("MUSIC_MAX_TRACKS", "12")):
        log.info("🎵 Müzik kütüphanesi tamam, yeni parça üretilmiyor")
        return
    generate_batch()


def send_to_telegram(only: str = "") -> int:
    """Kütüphanedeki parçaları (ya da sadece `only`) dinlemek için
    Telegram'a ses olarak gönderir."""
    from telegram_bot import _bot_token, _allowed_chat
    sent = 0
    for i, f in enumerate(tracks(), 1):
        if only and f.name != only:
            continue
        idx = int(f.stem.split("_")[-1]) if f.stem.split("_")[-1].isdigit() else 0
        desc = PROMPTS[idx - 1] if 0 < idx <= len(PROMPTS) else ""
        with open(f, "rb") as fh:
            r = requests.post(
                f"https://api.telegram.org/bot{_bot_token()}/sendAudio",
                data={"chat_id": _allowed_chat(), "title": f"Parça {i}",
                      "performer": "Fon müziği",
                      "caption": f"🎵 Parça {i} ({f.name})\n{desc}"},
                files={"audio": (f.name, fh, "audio/mpeg")}, timeout=120)
        if r.ok:
            sent += 1
        else:
            log.warning(f"Telegram sendAudio {r.status_code}: {r.text[:200]}")
    return sent


def best_start(path: str) -> float:
    """Parçanın uzun girişini atlamak için müziğin 'dolduğu' saniye:
    1 sn'lik pencerelerde ses gücü, parçanın tipik seviyesinin %70'ine
    ilk ulaştığı an. Sonuç library.json'da saklanır."""
    st = _load()
    starts = st.setdefault("starts", {})
    name = Path(path).name
    if name in starts:
        return starts[name]
    try:
        import subprocess
        import numpy as np
        import imageio_ffmpeg
        raw = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "quiet", "-i", path,
             "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
            capture_output=True, timeout=60).stdout
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        win = 8000
        rms = np.array([np.sqrt(np.mean(x[i:i + win] ** 2))
                        for i in range(0, len(x) - win, win)])
        target = 0.7 * np.percentile(rms, 75)
        hit = int(np.argmax(rms >= target)) if (rms >= target).any() else 0
        # Videoya en az 25 sn müzik kalsın
        start = float(min(hit, max(0, len(rms) - 25)))
    except Exception as e:
        log.warning(f"Müzik başlangıcı bulunamadı ({name}): {e}")
        start = 0.0
    starts[name] = start
    _save(st)
    return start


def replace(name: str) -> dict:
    """Bir parçayı kütüphaneden çıkarıp yerine yeni (kullanılmamış
    tarifli) bir parça üretir."""
    f = music_dir() / name
    if f.exists():
        f.unlink()
    st = _load()
    st.get("starts", {}).pop(name, None)
    st.setdefault("removed", []).append(name)
    _save(st)
    return generate_batch(1)
