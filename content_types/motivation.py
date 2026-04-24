"""
Motivasyon İçerik Tipi
Günlük motivasyon sözü / kısa düşünce. Kullanıcı konu seçebilir veya
otomatik rastgele bir kategori üzerinden üretilir.
"""

from datetime import datetime
from typing import Optional

from content_types.base import BaseContentType


# Önceden tanımlı motivasyon kategorileri
MOTIVATION_CATEGORIES = {
    "basari": {
        "name": "Başarı",
        "icon": "🏆",
        "emoji": "🏆",
        "color": "#f59e0b",
        "bg": "#1f1005",
        "subtitle": "Hedefe ulaşmak",
        "visual_queries": ["golden success mountain", "sunrise achievement",
                          "winner medal", "champion success"],
    },
    "odaklanma": {
        "name": "Odaklanma",
        "icon": "🎯",
        "emoji": "🎯",
        "color": "#ef4444",
        "bg": "#1f0a0a",
        "subtitle": "Dikkat ve hedefe yönelim",
        "visual_queries": ["arrow target bullseye", "focused concentration",
                          "zen meditation focus", "laser precision"],
    },
    "direnc": {
        "name": "Direnç",
        "icon": "💪",
        "emoji": "💪",
        "color": "#dc2626",
        "bg": "#1f0505",
        "subtitle": "Zorluklara karşı dayanıklılık",
        "visual_queries": ["storm lighthouse resilient", "strong tree wind",
                          "mountain climbing struggle", "warrior strength"],
    },
    "huzur": {
        "name": "Huzur",
        "icon": "🧘",
        "emoji": "🧘",
        "color": "#06b6d4",
        "bg": "#05181f",
        "subtitle": "İç dinginlik",
        "visual_queries": ["peaceful lake mountain", "calm forest morning",
                          "zen garden water", "sunset horizon peaceful"],
    },
    "sukran": {
        "name": "Şükran",
        "icon": "🙏",
        "emoji": "🙏",
        "color": "#eab308",
        "bg": "#1f1a05",
        "subtitle": "Minnet ve takdir",
        "visual_queries": ["sunrise gratitude hands", "golden light hope",
                          "nature flower beauty", "warm morning peaceful"],
    },
    "cesaret": {
        "name": "Cesaret",
        "icon": "🦁",
        "emoji": "🦁",
        "color": "#f97316",
        "bg": "#1f0f05",
        "subtitle": "Korkuya rağmen adım atmak",
        "visual_queries": ["lion brave roaring", "eagle flying mountain",
                          "jumping cliff adventure", "courage warrior"],
    },
    "sevgi": {
        "name": "Sevgi",
        "icon": "💝",
        "emoji": "💝",
        "color": "#ec4899",
        "bg": "#1f0a14",
        "subtitle": "Kalp ve bağ",
        "visual_queries": ["heart love romantic sunset", "couple love nature",
                          "flowers pink soft", "kindness people warm"],
    },
    "degisim": {
        "name": "Değişim",
        "icon": "🦋",
        "emoji": "🦋",
        "color": "#8b5cf6",
        "bg": "#15081f",
        "subtitle": "Dönüşüm ve yenilik",
        "visual_queries": ["butterfly transformation flower",
                          "phoenix rising fire", "season change autumn",
                          "caterpillar butterfly metamorphosis"],
    },
    "bilgelik": {
        "name": "Bilgelik",
        "icon": "📜",
        "emoji": "📜",
        "color": "#a78bfa",
        "bg": "#15081f",
        "subtitle": "Hayat dersleri",
        "visual_queries": ["old book library wisdom", "ancient scroll paper",
                          "philosophy statue thinker", "owl wise night"],
    },
    "umut": {
        "name": "Umut",
        "icon": "🌅",
        "emoji": "🌅",
        "color": "#fbbf24",
        "bg": "#1f1505",
        "subtitle": "Yeni başlangıçlar",
        "visual_queries": ["sunrise hope new day",
                          "light end tunnel dawn",
                          "spring blossom fresh", "rainbow after storm"],
    },
}


class MotivationType(BaseContentType):
    type_id = "motivation"
    type_name = "Motivasyon"
    type_icon = "💪"
    supports_auto = True       # Günde 1 rastgele kategori
    supports_manual = True     # Kullanıcı konu/kategori seçebilir

    def get_topics(self) -> list:
        """Motivasyon kategorileri."""
        topics = []
        for key, info in MOTIVATION_CATEGORIES.items():
            topics.append({
                "key": key,
                "name": info["name"],
                "icon": info["icon"],
                "emoji": info["emoji"],
                "subtitle": info["subtitle"],
                "meta": "",
                "color": info["color"],
            })
        return topics

    def build_prompt(self, topic_key: str,
                     custom_topic: str = None,
                     used_themes: list = None) -> str:
        """Motivasyon içeriği prompt'u."""
        today = datetime.now().strftime("%d %B %Y")
        used = ", ".join(used_themes[-10:]) if used_themes else "yok"

        # Kategori veya özel konu
        if custom_topic:
            topic_desc = f"Özel konu: {custom_topic}"
            topic_hint = custom_topic
        else:
            cat = MOTIVATION_CATEGORIES.get(topic_key, {})
            topic_desc = f"Kategori: {cat.get('name', 'Motivasyon')}"
            topic_hint = cat.get('name', 'motivasyon') + " - " + cat.get('subtitle', '')

        return f"""Sen derin düşünceli, sıcak ve ilham verici bir Türk motivasyon yazarısın.
YouTube Shorts için 60 saniyelik günlük motivasyon içeriği hazırlıyorsun.

Tarih: {today}
{topic_desc}

Bugün için {topic_hint} temalı, samimi ve içten bir motivasyon metni yaz.
Klişelerden kaçın (asla "başarabilirsin", "inan kendine" gibi bayat ifadeler
kullanma). Yerine somut, özgün ve derinliği olan bir mesaj ver.

Son kullanılan temalar (BUNLARI TEKRARLAMA): {used}

══════════════════════════════════════════════════════════════════
TÜRKÇE İMLA KURALLARI — KESİNLİKLE UYGULA
══════════════════════════════════════════════════════════════════
1. "de/da" bağlacı AYRI yazılır ("bugün de", "sen de").
2. "bir şey" ayrı, "hiçbir" birleşik, "hâlâ" şapkalı.
3. yalnış→yanlış, herkez→herkes, yanlız→yalnız, çünki→çünkü, birşey→bir şey.
4. Her cümle noktayla biter. Virgül ve noktadan sonra boşluk.
5. Rakamları yazıyla yaz (3→üç).
══════════════════════════════════════════════════════════════════

Sadece JSON döndür:
{{
  "title": "Çarpıcı başlık (max 80 karakter, merak uyandıran, emoji ile)",
  "hook": "İlk 3 saniye - dikkat çekici giriş cümlesi",
  "segments": [
    {{"time": "0-5s", "section": "hook", "text": "Kısa altyazı", "narration": "Giriş cümlesi - soru veya iddia"}},
    {{"time": "5-20s", "section": "gelisme", "text": "Kısa altyazı", "narration": "Ana düşünce - 2-3 cümle"}},
    {{"time": "20-35s", "section": "ornek", "text": "Kısa altyazı", "narration": "Somut örnek veya metafor"}},
    {{"time": "35-50s", "section": "icin", "text": "Kısa altyazı", "narration": "İçselleştirme - okuyucuya hitap"}},
    {{"time": "50-60s", "section": "kapanis", "text": "Kısa altyazı", "narration": "Güçlü kapanış cümlesi"}}
  ],
  "full_narration": "Tüm metin akıcı, 170-210 kelime.",
  "key_message": "Tek cümle — videonun ana mesajı",
  "author_style": "Anonim veya bir düşünür hissi (hayali)",
  "theme": "Kısa tema (3-5 kelime)",
  "description": "YouTube açıklaması (150-250 karakter)",
  "tags": ["motivasyon", "ilham", "günlük", "düşünce", "shorts"],
  "hashtags": ["#motivasyon", "#günlük", "#ilham", "#shorts", "#düşünce"]
}}

ÖNEMLİ: Metinlerde "sen/siz" zamirini kullan, okuyucuyla samimi bir bağ kur.
Ama "arkadaşım", "canım" gibi aşırı samimi hitap kullanma."""

    def get_visual_queries(self, topic_key: str,
                           content: dict = None) -> list:
        cat = MOTIVATION_CATEGORIES.get(topic_key, {})
        if cat.get("visual_queries"):
            return cat["visual_queries"] + [
                "inspiring sunrise mountain", "peaceful nature morning"]
        return ["inspiring nature golden", "motivation sunrise peaceful",
                "peaceful mountain dawn", "success mountain sky"]

    def get_theme_colors(self, topic_key: str,
                         content: dict = None) -> dict:
        cat = MOTIVATION_CATEGORIES.get(topic_key, {})
        return {
            "accent_color": cat.get("color", "#f59e0b"),
            "background_color": cat.get("bg", "#1f1005"),
        }

    def get_intro_text(self, topic_key: str, content: dict = None) -> str:
        cat = MOTIVATION_CATEGORIES.get(topic_key, {})
        return cat.get("name", "Günün Motivasyonu")

    def get_outro_text(self, topic_key: str, content: dict = None) -> str:
        return "Abone ol · Her gün yeni ilham"

    def get_lucky_card(self, topic_key: str, content: dict) -> Optional[dict]:
        """Motivasyon için lucky card yerine 'key message' gösterilebilir."""
        key_msg = content.get("key_message", "")
        if not key_msg:
            return None
        # Tek sütunlu kart — ana mesaj
        return {
            "single": ("GÜNÜN MESAJI", key_msg[:80]),
        }
