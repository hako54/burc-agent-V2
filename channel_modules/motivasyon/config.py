"""
Motivasyon Kanalı Konfigürasyonu
"""

CHANNEL_META = {
    "type_id": "motivation",
    "type_name": "Motivasyon",
    "icon": "💪",
    "description": "Günlük motivasyon sözleri ve düşünceler",
    "supports_auto": True,
    "supports_manual": True,
    "default_color": "#f59e0b",
}

# TTS — Rachel (daha duygusal, anlatımcı)
VOICE_CONFIG = {
    "voice_id": "21m00Tcm4TlvDq8ikWAM",
    "stability": 0.45,
    "style": 0.50,
    "speed": 0.96,
    "similarity_boost": 0.75,
}

VIDEO_STYLE = {
    "intro_style": "category_icon",
    "outro_style": "subscribe_cta",
    "subtitle_position": "center",
    "lucky_card": False,
    "has_section_badges": False,
}

# Motivasyon kategorileri
CATEGORIES = {
    "basari": {
        "name": "Başarı",
        "icon": "🏆", "emoji": "🏆",
        "color": "#f59e0b", "bg": "#1f1005",
        "subtitle": "Hedefe ulaşmak",
        "visual_queries": ["golden success mountain", "sunrise achievement",
                           "winner medal", "champion success"],
        "face_queries": [
            "beautiful young woman model glamorous portrait",
            "stunning woman fashion portrait makeup",
            "attractive woman confident close up",
            "beautiful woman elegant studio portrait",
        ],
    },
    "odaklanma": {
        "name": "Odaklanma",
        "icon": "🎯", "emoji": "🎯",
        "color": "#ef4444", "bg": "#1f0a0a",
        "subtitle": "Dikkat ve hedefe yönelim",
        "visual_queries": ["arrow target bullseye", "focused concentration",
                           "zen meditation focus", "laser precision"],
        "face_queries": [
            "beautiful young woman model intense gaze portrait",
            "stunning woman fashion makeup serious look",
            "gorgeous woman portrait dramatic lighting",
            "beautiful woman close up eyes intense",
        ],
    },
    "direnc": {
        "name": "Direnç",
        "icon": "💪", "emoji": "💪",
        "color": "#dc2626", "bg": "#1f0505",
        "subtitle": "Zorluklara karşı dayanıklılık",
        "visual_queries": ["storm lighthouse resilient", "strong tree wind",
                           "mountain climbing struggle", "warrior strength"],
        "face_queries": [
            "beautiful young woman model strong fierce portrait",
            "stunning woman bold powerful look makeup",
            "gorgeous woman dramatic portrait fashion",
            "attractive woman fierce gaze close up",
        ],
    },
    "huzur": {
        "name": "Huzur",
        "icon": "🧘", "emoji": "🧘",
        "color": "#06b6d4", "bg": "#05181f",
        "subtitle": "İç dinginlik",
        "visual_queries": ["peaceful lake mountain", "calm forest morning",
                           "zen garden water", "sunset horizon peaceful"],
        "face_queries": [
            "beautiful young woman model serene smile portrait",
            "stunning woman peaceful gentle portrait makeup",
            "gorgeous woman soft glamorous close up",
            "attractive woman calm beautiful portrait",
        ],
    },
    "sukran": {
        "name": "Şükran",
        "icon": "🙏", "emoji": "🙏",
        "color": "#eab308", "bg": "#1f1a05",
        "subtitle": "Minnet ve takdir",
        "visual_queries": ["sunrise gratitude hands", "golden light hope",
                           "nature flower beauty", "warm morning peaceful"],
        "face_queries": [
            "beautiful young woman model warm smile portrait",
            "stunning woman happy glamorous makeup close up",
            "gorgeous woman radiant smile portrait",
            "attractive woman golden hour beautiful",
        ],
    },
    "cesaret": {
        "name": "Cesaret",
        "icon": "🦁", "emoji": "🦁",
        "color": "#f97316", "bg": "#1f0f05",
        "subtitle": "Korkuya rağmen adım atmak",
        "visual_queries": ["lion brave roaring", "eagle flying mountain",
                           "jumping cliff adventure", "courage warrior"],
        "face_queries": [
            "beautiful young woman model bold portrait fashion",
            "stunning woman fierce confident makeup",
            "gorgeous woman dramatic powerful close up",
            "attractive woman strong elegant portrait",
        ],
    },
    "sevgi": {
        "name": "Sevgi",
        "icon": "💝", "emoji": "💝",
        "color": "#ec4899", "bg": "#1f0a14",
        "subtitle": "Kalp ve bağ",
        "visual_queries": ["heart love romantic sunset", "couple love nature",
                           "flowers pink soft", "kindness people warm"],
        "face_queries": [
            "beautiful young woman model romantic portrait pink",
            "stunning woman tender glamorous makeup",
            "gorgeous woman soft pink portrait fashion",
            "attractive woman romantic beautiful close up",
        ],
    },
    "degisim": {
        "name": "Değişim",
        "icon": "🦋", "emoji": "🦋",
        "color": "#8b5cf6", "bg": "#15081f",
        "subtitle": "Dönüşüm ve yenilik",
        "visual_queries": ["butterfly transformation flower",
                           "phoenix rising fire", "season change autumn",
                           "caterpillar butterfly metamorphosis"],
        "face_queries": [
            "beautiful young woman model artistic portrait colorful",
            "stunning woman creative makeup portrait fashion",
            "gorgeous woman dramatic transformation close up",
            "attractive woman vibrant portrait fashion",
        ],
    },
    "bilgelik": {
        "name": "Bilgelik",
        "icon": "📜", "emoji": "📜",
        "color": "#a78bfa", "bg": "#15081f",
        "subtitle": "Hayat dersleri",
        "visual_queries": ["old book library wisdom", "ancient scroll paper",
                           "philosophy statue thinker", "owl wise night"],
        "face_queries": [
            "beautiful young woman model thoughtful portrait elegant",
            "stunning woman pensive deep portrait makeup",
            "gorgeous woman intelligent close up fashion",
            "attractive woman elegant thoughtful portrait",
        ],
    },
    "umut": {
        "name": "Umut",
        "icon": "🌅", "emoji": "🌅",
        "color": "#fbbf24", "bg": "#1f1505",
        "subtitle": "Yeni başlangıçlar",
        "visual_queries": ["sunrise hope new day",
                           "light end tunnel dawn",
                           "spring blossom fresh", "rainbow after storm"],
        "face_queries": [
            "beautiful young woman model bright smile portrait",
            "stunning woman hopeful glamorous makeup",
            "gorgeous woman radiant golden portrait",
            "attractive woman optimistic beautiful close up",
        ],
    },
}
