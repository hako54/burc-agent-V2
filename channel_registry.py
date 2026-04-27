"""
Çoklu Kanal Yönetimi
Kanal tanımları data/channels.json'da tutulur. Her kanalın kendi
YouTube OAuth token'ı, veri klasörü ve içerik tipi vardır.

Kanal tipleri:
  - zodiac: Günlük 12 burç yorumu
  - custom: Serbest içerik (ileride genişletilebilir)
"""

import json
import logging
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
CHANNELS_FILE = DATA_DIR / "channels.json"
_lock = threading.Lock()

# Desteklenen kanal tipleri
CHANNEL_TYPES = {
    "zodiac": {
        "name": "Burç / Astroloji",
        "icon": "🔮",
        "description": "Günlük 12 burç yorumu",
        "auto_schedule": True,
    },
    "motivation": {
        "name": "Motivasyon",
        "icon": "💪",
        "description": "Günlük motivasyon sözleri ve düşünceler",
        "auto_schedule": True,
    },
}


def _default_channels() -> list:
    """Varsayılan tek bir burç kanalı."""
    return [
        {
            "id": "burc",
            "name": "Burç Kanalı",
            "type": "zodiac",
            "icon": "🔮",
            "color": "#d4af37",
            "youtube_url": os.environ.get("YOUTUBE_CHANNEL_URL", ""),
            "token_env": "TOKEN_BURC",
            "token_file": "token_burc.json",
            "data_subdir": "burc",
            "auto_schedule": True,
            "schedule_times": ["06:00"],
            "voice_id": "XB0fDUnXU5powFXDhCwa",   # Charlotte - sakin mistik
            "voice_stability": 0.50,
            "voice_style": 0.35,
            "voice_speed": 0.95,
            "created_at": datetime.now().isoformat(),
        }
    ]


# Content type'a göre önerilen voice default'ları
_TYPE_VOICE_DEFAULTS = {
    "zodiac": {
        "voice_id": "XB0fDUnXU5powFXDhCwa",  # Charlotte
        "voice_stability": 0.50,
        "voice_style": 0.35,
        "voice_speed": 0.95,
    },
    "motivation": {
        "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Rachel
        "voice_stability": 0.45,
        "voice_style": 0.50,    # daha duygusal
        "voice_speed": 0.96,
    },
    "custom": {
        "voice_id": "21m00Tcm4TlvDq8ikWAM",
        "voice_stability": 0.50,
        "voice_style": 0.40,
        "voice_speed": 1.00,
    },
}

# Content type'a göre varsayılan otomatik üretim saatleri
_TYPE_DEFAULT_SCHEDULE = {
    "zodiac": ["06:00"],
    "motivation": ["10:30", "19:00"],
    "custom": ["10:00"],
}


def _validate_time(s: str) -> str:
    """'HH:MM' formatını kontrol eder ve normalize eder. Geçersizse hata."""
    s = (s or "").strip()
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"Geçersiz saat: '{s}' (HH:MM olmalı)")
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        raise ValueError(f"Geçersiz saat: '{s}'")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Geçersiz saat: '{s}'")
    return f"{h:02d}:{m:02d}"


def _normalize_schedule(times, channel_type: str) -> list:
    """Saat listesini doğrula, normalize et, sıralı tutarlı dön.
    Boşsa type default'unu kullan."""
    if not times:
        return list(_TYPE_DEFAULT_SCHEDULE.get(channel_type, ["10:00"]))
    if isinstance(times, str):
        times = [t.strip() for t in times.split(",") if t.strip()]
    cleaned = []
    seen = set()
    for t in times:
        try:
            normalized = _validate_time(t)
            if normalized not in seen:
                seen.add(normalized)
                cleaned.append(normalized)
        except ValueError as e:
            log.warning(f"Skipping invalid time: {e}")
    if not cleaned:
        return list(_TYPE_DEFAULT_SCHEDULE.get(channel_type, ["10:00"]))
    cleaned.sort()
    return cleaned


def _load_channels() -> list:
    """Kanal listesini JSON'dan yükle. Yoksa default dön."""
    if CHANNELS_FILE.exists():
        try:
            return json.loads(CHANNELS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"channels.json parse hatası: {e}")
    return _default_channels()


def _save_channels(channels: list):
    CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHANNELS_FILE.write_text(
        json.dumps(channels, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_channels() -> list:
    """Tanımlı tüm kanalların listesi."""
    with _lock:
        channels = _load_channels()
        # Migration: eski kayıtların schedule_times'ı yoksa default ekle
        modified = False
        for ch in channels:
            if "schedule_times" not in ch:
                ch["schedule_times"] = list(_TYPE_DEFAULT_SCHEDULE.get(
                    ch.get("type", "custom"), ["10:00"]
                ))
                modified = True
            subdir = DATA_DIR / ch.get("data_subdir", ch["id"])
            subdir.mkdir(parents=True, exist_ok=True)
        if modified:
            _save_channels(channels)
        return channels


def get_channel(channel_id: str) -> Optional[dict]:
    for ch in list_channels():
        if ch["id"] == channel_id:
            return ch
    return None


def add_channel(channel_id: str, name: str, channel_type: str,
                youtube_url: str = "", color: str = "#d4af37",
                auto_schedule: bool = False,
                schedule_times: list = None,
                voice_id: str = "",
                voice_stability: float = None,
                voice_style: float = None,
                voice_speed: float = None) -> dict:
    """Yeni kanal ekle.

    schedule_times: ['HH:MM', 'HH:MM', ...] — günde kaç kez ve hangi saatte
        otomatik üretim yapılacağı. Boş/None ise default kullanılır:
        - zodiac: ['06:00']
        - motivation: ['10:30', '19:00']
        - custom: ['10:00']
    """
    if channel_type not in CHANNEL_TYPES:
        raise ValueError(
            f"Geçersiz tip: {channel_type}. "
            f"Geçerli: {', '.join(CHANNEL_TYPES.keys())}"
        )

    channel_id = "".join(
        c if c.isalnum() or c == "-" else "-"
        for c in channel_id.lower().strip()
    )
    if not channel_id:
        raise ValueError("Geçerli bir kanal ID'si ver")

    # Content type'a göre voice default'ları
    voice_defaults = _TYPE_VOICE_DEFAULTS.get(
        channel_type, _TYPE_VOICE_DEFAULTS["custom"]
    )

    with _lock:
        channels = _load_channels()
        if any(c["id"] == channel_id for c in channels):
            raise ValueError(f"'{channel_id}' ID'li kanal zaten var")

        token_env = f"TOKEN_{channel_id.upper().replace('-', '_')}"
        token_file = f"token_{channel_id}.json"

        new_channel = {
            "id": channel_id,
            "name": name,
            "type": channel_type,
            "icon": CHANNEL_TYPES[channel_type]["icon"],
            "color": color,
            "youtube_url": youtube_url,
            "token_env": token_env,
            "token_file": token_file,
            "data_subdir": channel_id,
            "auto_schedule": bool(auto_schedule),
            "schedule_times": _normalize_schedule(schedule_times,
                                                  channel_type),
            "voice_id": voice_id or voice_defaults["voice_id"],
            "voice_stability": (voice_stability
                               if voice_stability is not None
                               else voice_defaults["voice_stability"]),
            "voice_style": (voice_style
                           if voice_style is not None
                           else voice_defaults["voice_style"]),
            "voice_speed": (voice_speed
                           if voice_speed is not None
                           else voice_defaults["voice_speed"]),
            "created_at": datetime.now().isoformat(),
        }
        channels.append(new_channel)
        _save_channels(channels)

        (DATA_DIR / channel_id).mkdir(parents=True, exist_ok=True)

        log.info(f"Yeni kanal eklendi: {channel_id}")
        return new_channel


def update_channel(channel_id: str, **updates) -> dict:
    """Kanal bilgilerini güncelle."""
    allowed = {
        "name", "youtube_url", "color", "auto_schedule", "schedule_times",
        "voice_id", "voice_stability", "voice_style", "voice_speed",
    }
    with _lock:
        channels = _load_channels()
        for ch in channels:
            if ch["id"] == channel_id:
                for k, v in updates.items():
                    if k in allowed and v is not None:
                        # schedule_times için doğrula+normalize
                        if k == "schedule_times":
                            v = _normalize_schedule(v, ch.get("type", "custom"))
                        ch[k] = v
                _save_channels(channels)
                return ch
        raise ValueError(f"Kanal bulunamadı: {channel_id}")


def remove_channel(channel_id: str) -> dict:
    """Kanal sil (veri klasörüne dokunmaz, sadece tanımı siler)."""
    with _lock:
        channels = _load_channels()
        channel = next((c for c in channels if c["id"] == channel_id), None)
        if not channel:
            raise ValueError(f"Kanal bulunamadı: {channel_id}")
        if channel_id == "burc":
            raise ValueError("Varsayılan burç kanalı silinemez")
        channels = [c for c in channels if c["id"] != channel_id]
        _save_channels(channels)
        log.info(f"Kanal silindi: {channel_id}")
        return channel


def channel_data_dir(channel_id: str) -> Path:
    """Bir kanalın veri klasörünü döner (data/<channel_id>/)."""
    channel = get_channel(channel_id)
    if not channel:
        raise ValueError(f"Kanal bulunamadı: {channel_id}")
    path = DATA_DIR / channel.get("data_subdir", channel_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
