"""
Burç (Zodiac) İçerik Tipi
12 burç için günlük yorum üretir. Mevcut sistemin devamıdır.
"""

from datetime import datetime
from typing import Optional

from zodiac import ZODIAC_SIGNS, normalize_sign, get_sign, all_sign_keys
from content_types.base import BaseContentType


class ZodiacType(BaseContentType):
    type_id = "zodiac"
    type_name = "Burç / Astroloji"
    type_icon = "🔮"
    supports_auto = True       # Scheduler gün aşırı 6 burç üretir
    supports_manual = True     # Kullanıcı tek burç da seçebilir

    def get_topics(self) -> list:
        """12 burç, dashboard grid için."""
        topics = []
        for key in all_sign_keys():
            info = get_sign(key)
            topics.append({
                "key": key,
                "name": info["name"],
                "icon": info["symbol"],
                "emoji": info["emoji"],
                "subtitle": info["dates"],
                "meta": info["element"],
                "color": info["color"],
            })
        return topics

    def build_prompt(self, topic_key: str,
                     custom_topic: str = None,
                     used_themes: list = None) -> str:
        """Burç için günlük yorum prompt'u."""
        info = get_sign(topic_key)
        today = datetime.now().strftime("%d %B %Y")
        used = ", ".join(used_themes[-10:]) if used_themes else "yok"

        return f"""Sen profesyonel bir Türk astroloğusun. YouTube Shorts için 60 saniyelik
günlük burç yorumu hazırlıyorsun.

Tarih: {today}
Burç: {info['name']} {info['symbol']} ({info['dates']})
Element: {info['element']}, Yönetici: {info['ruler']}
Özellikler: {info['traits']}

Bugün için pozitif ama gerçekçi, enerji veren, motive edici ama abartısız
bir günlük yorum yaz. Astroloji dilini akıcı Türkçe kullan, klişelerden kaçın.

Son kullanılan temalar (BUNLARI TEKRARLAMA): {used}

══════════════════════════════════════════════════════════════════
TÜRKÇE İMLA KURALLARI — KESİNLİKLE UYGULA
══════════════════════════════════════════════════════════════════
1. BAĞLAÇLAR: "de/da" bağlacı AYRI yazılır ("bugün de"). "ki" ve "mi" de ayrı.
2. BİRLEŞİK: "bir şey" (ayrı), "hiçbir", "herkes", "hâlâ" (şapkalı).
3. YAYGIN HATALAR: yalnış→yanlış, herkez→herkes, yanlız→yalnız,
   çünki→çünkü, birşey→bir şey, herşey→her şey.
4. NOKTALAMA: Her cümle nokta/soru/ünlem ile bitsin. Virgül ve noktadan
   sonra boşluk bırak.
5. TTS: Rakamları yazıyla yaz (3→üç).
══════════════════════════════════════════════════════════════════

Sadece JSON döndür:
{{
  "title": "Başlık (max 90 karakter, burç adı + tarih + emoji ile)",
  "hook": "İlk 3 saniye - giriş cümlesi",
  "segments": [
    {{"time": "0-4s", "section": "giris", "text": "Kısa altyazı", "narration": "TTS metni"}},
    {{"time": "4-15s", "section": "genel", "text": "Kısa altyazı", "narration": "Günün genel yorumu"}},
    {{"time": "15-28s", "section": "ask", "text": "💕 Aşk", "narration": "Aşk yorumu"}},
    {{"time": "28-40s", "section": "kariyer", "text": "💼 Kariyer", "narration": "Kariyer yorumu"}},
    {{"time": "40-50s", "section": "saglik", "text": "🌿 Sağlık", "narration": "Sağlık yorumu"}},
    {{"time": "50-60s", "section": "sans", "text": "✨ Şanslı", "narration": "Şanslı sayı, renk, uyumlu burç"}}
  ],
  "full_narration": "Tüm anlatım metni (TTS yedek)",
  "lucky_number": "1-99 arası tek sayı",
  "lucky_color": "Şanslı renk (Türkçe)",
  "compatible_sign": "Uyumlu burç (12 burçtan biri)",
  "theme": "Kısa tema (3-5 kelime)",
  "description": "YouTube açıklaması (200-300 karakter)",
  "tags": ["burç", "{info['name'].lower()}", "günlük", "astroloji", "shorts"],
  "hashtags": ["#{info['name'].lower()}burcu", "#günlükburç", "#astroloji", "#shorts"]
}}"""

    def get_visual_queries(self, topic_key: str,
                           content: dict = None) -> list:
        info = get_sign(topic_key)
        return info["visual_queries"] + [
            f"zodiac {info['en_name']} mystical",
            "astrology stars cosmic",
        ]

    def get_theme_colors(self, topic_key: str,
                         content: dict = None) -> dict:
        info = get_sign(topic_key)
        return {
            "accent_color": info["color"],
            "background_color": info["bg"],
        }

    def get_intro_text(self, topic_key: str, content: dict = None) -> str:
        info = get_sign(topic_key)
        return f"{info['name']} burcu günlük yorum"

    def get_lucky_card(self, topic_key: str, content: dict) -> Optional[dict]:
        return {
            "col1": ("ŞANSLI SAYI", content.get("lucky_number", "")),
            "col2": ("ŞANSLI RENK", content.get("lucky_color", "")),
            "col3": ("UYUMLU BURÇ", content.get("compatible_sign", "")),
        }
