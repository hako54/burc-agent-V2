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
        # Her kanalın veri klasörü yoksa oluştur
        for ch in channels:
            subdir = DATA_DIR / ch.get("data_subdir", ch["id"])
            subdir.mkdir(parents=True, exist_ok=True)
        return channels


def get_channel(channel_id: str) -> Optional[dict]:
    for ch in list_channels():
        if ch["id"] == channel_id:
            return ch
    return None


def add_channel(channel_id: str, name: str, channel_type: str,
                youtube_url: str = "", color: str = "#d4af37",
                auto_schedule: bool = False,
                voice_id: str = "",
                voice_stability: float = None,
                voice_style: float = None,
                voice_speed: float = None) -> dict:
    """Yeni kanal ekle."""
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
        "name", "youtube_url", "color", "auto_schedule",
        "voice_id", "voice_stability", "voice_style", "voice_speed",
    }
    with _lock:
        channels = _load_channels()
        for ch in channels:
            if ch["id"] == channel_id:
                for k, v in updates.items():
                    if k in allowed and v is not None:
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
