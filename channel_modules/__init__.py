"""
Kanal Modülleri Paketi
Her kanal kendi klasöründe yaşar:
  channel_modules/<id>/
    config.py       # Meta, voice, colors
    content.py      # get_topics(), build_prompt()
    video_template.py  # intro_clip(), outro_clip(), subtitle_style()

Modüller "type" anahtarıyla da eşleşebilir; yeni kanal eklerken onun
modülü yoksa "type" bazlı default modül kullanılır.
"""

import importlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Her "type" için varsayılan modül (yeni kanal eklendiğinde kendi klasörü
# yoksa bu kullanılır).
_TYPE_DEFAULTS = {
    "zodiac": "channel_modules.burc",
    "motivation": "channel_modules.motivasyon",
    "soz": "channel_modules.soz",
    "custom": "channel_modules.motivasyon",  # şimdilik motivasyon gibi
}

# Yüklü modül cache'i
_loaded_modules: dict = {}


def load_module(channel_id: str, channel_type: str = "zodiac"):
    """Bir kanal için uygun modülü yükler.
    Önce channel_modules/<channel_id>/ arar,
    yoksa type'a göre default modüle düşer."""
    cache_key = f"{channel_id}:{channel_type}"
    if cache_key in _loaded_modules:
        return _loaded_modules[cache_key]

    # Önce kanal-özel modül var mı?
    custom_path = f"channel_modules.{channel_id.replace('-', '_')}"
    try:
        module = importlib.import_module(custom_path)
        log.info(f"Kanal modülü yüklendi: {custom_path}")
        _loaded_modules[cache_key] = module
        return module
    except ImportError:
        pass

    # Type'a göre default
    default_path = _TYPE_DEFAULTS.get(channel_type, _TYPE_DEFAULTS["zodiac"])
    try:
        module = importlib.import_module(default_path)
        log.info(f"Default modül yüklendi: {default_path}")
        _loaded_modules[cache_key] = module
        return module
    except ImportError as e:
        log.error(f"Hiçbir modül yüklenemedi: {e}")
        raise


def reset_cache():
    """Test için cache'i temizle."""
    _loaded_modules.clear()
