"""
Söz Kanalı Konfigürasyonu
─────────────────────────
Söz mood'una göre Lina'nın hangi temada görüneceğini belirler.
Her tema 3 farklı varyant (look_id) içerir — rastgele seçim için.

HeyGen avatar grubu: Lina (sarışın manken karakter)
HeyGen ses: Charming Ceyda (Türkçe, kadın, samimi)
"""

CHANNEL_META = {
    "type_id": "soz",
    "type_name": "Söz / Özlü Söz",
    "icon": "💭",
    "description": "AI avatarlı günlük özlü sözler (HeyGen)",
    "supports_auto": True,
    "supports_manual": True,
    "default_color": "#c084fc",
}

# HeyGen API bilgileri
HEYGEN_CONFIG = {
    "avatar_group_id": "0cfb78ab1ade4a178af487e851a8dd2a",  # Lina
    "voice_id": "8bb2c6f55b64448588b5dfc403ab2374",  # Charming Ceyda
    "voice_name": "Charming Ceyda",
    "speed": 1.0,
    "talking_photo_style": "stable",  # 'stable' veya 'expressive'
    "width": 1080,
    "height": 1920,  # Shorts (dikey)
}

# ────────────────────────────────────────────────────────────────────
# Tema kütüphanesi
# ────────────────────────────────────────────────────────────────────
# Her tema:
#   moods: bu temayla EŞLEŞEN mood etiketleri
#   look_ids: HeyGen'deki Photo Avatar look ID'leri (varyantlar)
#
# Söz LLM'e yazdırılırken mood etiketleri seçtirilir, sonra burada
# en çok mood eşleşmesi olan tema seçilir.
# ────────────────────────────────────────────────────────────────────

THEMES = {
    "akdeniz_kafe": {
        "name": "Akdeniz Kafesi",
        "icon": "☕",
        "description": "Beyaz keten gömlek, kafe terası, sıcak öğle ışığı",
        "moods": [
            "sohbet", "paylasim", "samimiyet", "dostluk", "iliski",
            "yakin_baglar", "bag", "anlam", "muhabbet",
        ],
        "look_ids": [
            "d8d85fc2b41f4b7abbbf56cb834bc92d",
            "c699fcc4da734d99905340d4c1242406",
            "835a7a349bb74ddca72e14483357e14f",
        ],
    },
    "mykonos_sahili": {
        "name": "Mykonos Sahili",
        "icon": "🏖️",
        "description": "Krem yazlık elbise, deniz kıyısı, esinti",
        "moods": [
            "ozgurluk", "ferahlik", "baslangic", "hayal", "ufuk",
            "deniz", "engin", "kucagini_acmak", "savrulma", "rüya",
        ],
        "look_ids": [
            "d715b3eda88044f9b5c5a3c05a00b04a",
            "2594e2097432414888092f8e84269cec",
            "db0264ac8fb34735825a77b0b52decd2",
        ],
    },
    "sonbahar_gol": {
        "name": "Sonbahar Göl İskelesi",
        "icon": "🏞️",
        "description": "Krem örgü kazak, sisli göl, sakin sabah",
        "moods": [
            "huzur", "sukunet", "kabul", "ice_donus", "icsel_baris",
            "sessizlik", "derinlik", "tefekkur", "yalnizlik_iyi",
            "donus", "icsellik",
        ],
        "look_ids": [
            "f7d50c88f7d8479cb33bc7a339073ee5",
            "64a60f310e2c4f88946544917c4b2462",
            "464e696f21e9436995b72814d92d7293",
        ],
    },
    "sonbahar_sokak": {
        "name": "Sonbahar Avrupa Sokağı",
        "icon": "🏙️",
        "description": "Deri ceket, taş döşeli sokak, sonbahar yaprakları",
        "moods": [
            "irade", "kararlilik", "ilerleme", "guc", "cesaret",
            "icsel_guc", "azim", "sebat", "dik_durus", "olgunluk",
            "bilgelik", "tecrube",
        ],
        "look_ids": [
            "9c7370559b4c465fbc330685fb100cc2",
            "2156b6dda96b4589a4d4dcd6bbcb3228",
            "18d1e0eaa3af4efd85cad4918d5e35c1",
        ],
    },
    "lavanta_tarlasi": {
        "name": "Lavanta Tarlası",
        "icon": "💜",
        "description": "Vintage çiçekli elbise, mor lavanta, gün batımı",
        "moods": [
            "sukur", "guzellik", "mutluluk", "doga", "kucuk_seyler",
            "minnet", "ferah", "huzur_dolu", "anlik", "sade_guzellik",
            "an_yasama",
        ],
        "look_ids": [
            "ddb8878183a647c9ae74be47f3626900",
            "cceb53f1b9ae41708d8cdfadf6cc7f11",
            "0eba9470ea184066933494be4e9122a8",
        ],
    },
    "yaz_sokak": {
        "name": "Yaz Avrupa Sokağı",
        "icon": "☀️",
        "description": "Pastel sarı elbise, güneşli yaz, çiçekli balkonlar",
        "moods": [
            "umut", "nese", "yenilenme", "baslangic_yaz", "sevinc",
            "canlilik", "isik", "icimde_bahar", "tazelik", "iyimserlik",
            "merak", "kesif",
        ],
        "look_ids": [
            "b3be62a64b6e4d8a89ab3ff88040f4b6",
            "8f58b34b9d5b4554aca25d2b3f519bb6",
            "1d1e80e2663f48e58e233f5e6a2638e9",
        ],
    },
    "studyo": {
        "name": "Modern Stüdyo",
        "icon": "🏠",
        "description": "Beyaz gömlek + jean, iç mekan, modern",
        "moods": [
            "gunluk", "samimi", "modern", "sade", "bireysel", "kisisel",
        ],
        "look_ids": [
            "0cfb78ab1ade4a178af487e851a8dd2a",
        ],
    },
}


def all_mood_tags() -> list:
    """Tüm benzersiz mood etiketleri (LLM'e seçim için verilecek liste)."""
    tags = set()
    for theme in THEMES.values():
        tags.update(theme["moods"])
    return sorted(tags)
