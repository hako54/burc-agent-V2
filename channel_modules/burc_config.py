"""
Burç Kanalı Konfigürasyonu
Ses, renk, ve genel meta bilgiler.
"""

CHANNEL_META = {
    "type_id": "zodiac",
    "type_name": "Burç / Astroloji",
    "icon": "🔮",
    "description": "Günlük 12 burç yorumu",
    "supports_auto": True,
    "supports_manual": True,
    "default_color": "#d4af37",
}

# TTS ses ayarları — Charlotte (sakin, mistik)
VOICE_CONFIG = {
    "voice_id": "XB0fDUnXU5powFXDhCwa",
    "stability": 0.50,
    "style": 0.35,
    "speed": 0.95,
    "similarity_boost": 0.75,
}

# Video template tercihleri
VIDEO_STYLE = {
    "intro_style": "zodiac_symbol",  # Büyük burç sembolü göster
    "outro_style": "subscribe_cta",
    "subtitle_position": "center",
    "lucky_card": True,               # Alt kartı göster (şanslı sayı/renk)
    "has_section_badges": True,       # 💕 Aşk, 💼 Kariyer rozetleri
}
