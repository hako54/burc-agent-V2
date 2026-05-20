"""
Söz Kanalı Konfigürasyonu
─────────────────────────
Stok video (Pexels) + ElevenLabs TTS + FFmpeg pipeline.

Söz LLM'in mood'una göre tema seçilir (match_theme), tema'nın
visual_queries'inden Pexels arar, sonuç olarak tam cinematic
video üretir.

(HeyGen Avatar IV tabanlı eski sistem ileride yeniden açılabilir
— heygen.py duruyor ama bu pipeline'da kullanılmıyor.)
"""

CHANNEL_META = {
    "type_id": "soz",
    "type_name": "Söz / Özlü Söz",
    "icon": "💭",
    "description": "Cinematic stok görsellerle günlük özlü sözler",
    "supports_auto": True,
    "supports_manual": True,
    "default_color": "#c084fc",
}

# TTS — kullanıcı channels.json'da kendi voice_id'sini geçiyor.
# Bu sadece fallback default.
VOICE_CONFIG = {
    "voice_id": "cgSgspJ2msm6clMCkdW9",  # warm female (kullanıcının default'u)
    "stability": 0.45,
    "style": 0.50,
    "speed": 0.95,
    "similarity_boost": 0.75,
}

VIDEO_STYLE = {
    "intro_style": "theme_icon",
    "outro_style": "subscribe_cta",
    "subtitle_position": "center",
    "lucky_card": True,
    "has_section_badges": False,
}

# ────────────────────────────────────────────────────────────────────
# Tema kütüphanesi — her tema bir görsel atmosfer + mood etiketleri
# ────────────────────────────────────────────────────────────────────
# moods: LLM hangi tema'ya uyduğunu belirlemek için (match_theme)
# visual_queries: Pexels/Pixabay'da aranacak terimler
# face_queries: Intro için kadın yüzü (motivasyon pattern'i)
# ────────────────────────────────────────────────────────────────────

THEMES = {
    "akdeniz_kafe": {
        "name": "Akdeniz Kafesi",
        "icon": "☕", "emoji": "☕",
        "color": "#d4a574", "bg": "#1f1505",
        "subtitle": "Kafe terası, sıcak öğle ışığı",
        "moods": [
            "sohbet", "paylasim", "samimiyet", "dostluk", "iliski",
            "yakin_baglar", "bag", "anlam", "muhabbet",
        ],
        "visual_queries": [
            "mediterranean cafe terrace warm light",
            "cozy coffee shop morning sun",
            "old town cafe table flowers",
            "rustic mediterranean cafe atmosphere",
            "warm afternoon coffee aesthetic",
        ],
        "face_queries": [
            "beautiful young blonde woman warm smile portrait",
            "stunning blonde woman natural casual portrait",
            "gorgeous blonde woman gentle close up",
            "attractive blonde woman warm friendly portrait",
        ],
    },
    "mykonos_sahili": {
        "name": "Mykonos Sahili",
        "icon": "🏖️", "emoji": "🏖️",
        "color": "#06b6d4", "bg": "#051820",
        "subtitle": "Deniz kıyısı, yaz esintisi",
        "moods": [
            "ozgurluk", "ferahlik", "baslangic", "hayal", "ufuk",
            "deniz", "engin", "kucagini_acmak", "savrulma", "ruya",
        ],
        "visual_queries": [
            "mediterranean beach sea blue summer",
            "greek island white house sea view",
            "ocean horizon sunset peaceful",
            "white sand beach blue water aerial",
            "summer mediterranean coast cinematic",
        ],
        "face_queries": [
            "beautiful young blonde woman beach summer portrait",
            "stunning blonde woman sea breeze natural",
            "gorgeous blonde woman summer dress aesthetic",
            "attractive blonde woman beach freedom portrait",
        ],
    },
    "sonbahar_gol": {
        "name": "Sonbahar Göl İskelesi",
        "icon": "🏞️", "emoji": "🏞️",
        "color": "#a78bfa", "bg": "#15081f",
        "subtitle": "Sisli göl, sakin sabah",
        "moods": [
            "huzur", "sukunet", "kabul", "ice_donus", "icsel_baris",
            "sessizlik", "derinlik", "tefekkur", "yalnizlik_iyi",
            "donus", "icsellik",
        ],
        "visual_queries": [
            "misty lake autumn morning peaceful",
            "foggy mountain lake sunrise calm",
            "autumn forest lake reflection serene",
            "quiet lake morning mist trees",
            "peaceful lake pier autumn cinematic",
        ],
        "face_queries": [
            "beautiful young blonde woman thoughtful portrait autumn",
            "stunning blonde woman pensive deep close up",
            "gorgeous blonde woman serene peaceful portrait",
            "attractive blonde woman quiet contemplative",
        ],
    },
    "sonbahar_sokak": {
        "name": "Sonbahar Avrupa Sokağı",
        "icon": "🏙️", "emoji": "🏙️",
        "color": "#dc2626", "bg": "#1f0505",
        "subtitle": "Taş sokak, sonbahar yaprakları",
        "moods": [
            "irade", "kararlilik", "ilerleme", "guc", "cesaret",
            "icsel_guc", "azim", "sebat", "dik_durus", "olgunluk",
            "bilgelik", "tecrube",
        ],
        "visual_queries": [
            "european old town autumn street cobblestone",
            "paris autumn fall leaves street cinematic",
            "european city autumn morning fog",
            "vintage european alley fall colors",
            "cobblestone street autumn warm light",
        ],
        "face_queries": [
            "beautiful young blonde woman leather jacket portrait",
            "stunning blonde woman confident street portrait",
            "gorgeous blonde woman determined fashion",
            "attractive blonde woman strong elegant urban",
        ],
    },
    "lavanta_tarlasi": {
        "name": "Lavanta Tarlası",
        "icon": "💜", "emoji": "💜",
        "color": "#c084fc", "bg": "#15081f",
        "subtitle": "Mor lavanta, gün batımı",
        "moods": [
            "sukur", "guzellik", "mutluluk", "doga", "kucuk_seyler",
            "minnet", "ferah", "huzur_dolu", "anlik", "sade_guzellik",
            "an_yasama",
        ],
        "visual_queries": [
            "lavender field purple sunset cinematic",
            "provence lavender flowers golden hour",
            "purple flower meadow sky sunset",
            "lavender field aerial cinematic warm",
            "blooming lavender countryside peaceful",
        ],
        "face_queries": [
            "beautiful young blonde woman summer dress portrait",
            "stunning blonde woman wildflowers natural",
            "gorgeous blonde woman radiant smile golden",
            "attractive blonde woman happy warm sunset",
        ],
    },
    "yaz_sokak": {
        "name": "Yaz Avrupa Sokağı",
        "icon": "☀️", "emoji": "☀️",
        "color": "#fbbf24", "bg": "#1f1505",
        "subtitle": "Güneşli yaz, çiçekli balkonlar",
        "moods": [
            "umut", "nese", "yenilenme", "baslangic_yaz", "sevinc",
            "canlilik", "isik", "icimde_bahar", "tazelik", "iyimserlik",
            "merak", "kesif",
        ],
        "visual_queries": [
            "european summer street flowers balcony",
            "italian alley summer warm light",
            "mediterranean village summer sunlight",
            "sunny european street blue sky flowers",
            "vibrant summer european cafe street",
        ],
        "face_queries": [
            "beautiful young blonde woman summer dress sunny",
            "stunning blonde woman happy bright smile portrait",
            "gorgeous blonde woman summer joyful natural",
            "attractive blonde woman radiant fresh portrait",
        ],
    },
    "studyo": {
        "name": "Modern Stüdyo",
        "icon": "🏠", "emoji": "🏠",
        "color": "#94a3b8", "bg": "#0f1419",
        "subtitle": "Modern, sade iç mekan",
        "moods": [
            "gunluk", "samimi", "modern", "sade", "bireysel", "kisisel",
        ],
        "visual_queries": [
            "modern minimalist interior home aesthetic",
            "cozy reading corner natural light",
            "minimal scandinavian living room peaceful",
            "soft morning light home interior",
        ],
        "face_queries": [
            "beautiful young blonde woman casual home portrait",
            "stunning blonde woman natural relaxed close up",
            "gorgeous blonde woman simple elegant portrait",
            "attractive blonde woman warm casual indoor",
        ],
    },
}


def all_mood_tags() -> list:
    """Tüm benzersiz mood etiketleri (LLM'e seçim listesi olarak verilir)."""
    tags = set()
    for theme in THEMES.values():
        tags.update(theme["moods"])
    return sorted(tags)


# ── HeyGen config (B seçeneğine dönülürse açılır) ──
# HEYGEN_CONFIG = {
#     "avatar_group_id": "0cfb78ab1ade4a178af487e851a8dd2a",  # Lina
#     "voice_id": "8bb2c6f55b64448588b5dfc403ab2374",  # Charming Ceyda
#     ...
# }
