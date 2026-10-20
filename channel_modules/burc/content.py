"""
Burç İçerik Modülü
12 burç için prompt, visual, theme color vb. sağlar.
"""

from services.tr_locale import tr_date, tr_lower
from typing import Optional

from zodiac import ZODIAC_SIGNS, get_sign, all_sign_keys


def get_topics() -> list:
    """12 burç — dashboard grid için."""
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


def build_prompt(topic_key: str, custom_topic: str = None,
                 used_themes: list = None) -> str:
    """12 burç için günlük yorum prompt'u."""
    info = get_sign(topic_key)
    today = tr_date()
    short_date = " ".join(today.split()[:2])  # "18 Ekim"
    used = ", ".join(used_themes[-10:]) if used_themes else "yok"

    return f"""Sen profesyonel bir Türk astroloğusun. YouTube Shorts için 45 saniyelik
günlük burç yorumu hazırlıyorsun. İzleyici ilk iki saniyede kaydırıp
geçmesin diye yorum merak uyandıran bir vaatle başlar ve kısa tutulur.

Tarih: {today}
Burç: {info['name']} {info['symbol']} ({info['dates']})
Element: {info['element']}, Yönetici: {info['ruler']}
Özellikler: {info['traits']}

Bugün için pozitif ama gerçekçi, enerji veren, motive edici ama abartısız
bir günlük yorum yaz. Astroloji dilini akıcı Türkçe kullan, klişelerden kaçın.

Son kullanılan temalar (BUNLARI TEKRARLAMA): {used}

══════════════════════════════════════════════════════════════════
TÜRKÇE İMLA — UY
══════════════════════════════════════════════════════════════════
1. "de/da", "ki", "mi" AYRI: "bugün de", "inan ki", "olur mu"
2. "bir şey" ayrı, "hiçbir" birleşik, "hâlâ" şapkalı
3. YANLIŞ YAZIMLAR: yalnış→yanlış, herkez→herkes, birşey→bir şey,
   çünki→çünkü, eğerki→eğer
4. Her cümle nokta/ünlem/soruyla biter. Noktalama sonrası boşluk.
5. Rakamları yazıyla (3→üç)
══════════════════════════════════════════════════════════════════

UZUNLUK (KRİTİK): Tüm "narration" alanlarının toplamı EN FAZLA 100 KELİME.
Her segment 1-2 kısa cümle. Gereksiz giriş, tekrar ve dolgu yok.

Sadece JSON döndür:
{{
  "title": "YouTube başlığı (max 80 karakter). Biçim: '{info['name']} {info['symbol']} <merak uyandıran vaat> <emoji> | {short_date}'. Vaat somut ve kişisel olsun (örn. 'Bugün Biri Sana İçini Açacak'). Tarih EN SONDA.",
  "hook": "İlk cümle - izleyiciyi durduran somut vaat (burç adı geçsin)",
  "hook_text": "Ekranda dev harflerle çıkacak 3-5 kelimelik merak cümlesi; NORMAL yazımla yaz, büyük harfe sistem çevirir (burç adı YOK, örn. 'Bugün biri sana açılacak')",
  "segments": [
    {{"section": "giris", "text": "Kısa altyazı", "narration": "Hook cümlesi (en fazla 12 kelime)"}},
    {{"section": "genel", "text": "Kısa altyazı", "narration": "Genel enerji (en fazla 25 kelime)"}},
    {{"section": "ask", "text": "💕 Aşk", "narration": "Aşk (en fazla 22 kelime)"}},
    {{"section": "kariyer", "text": "💼 Kariyer", "narration": "Kariyer/para (en fazla 22 kelime)"}},
    {{"section": "sans", "text": "✨ Şanslı", "narration": "Şanslı sayı, renk, uyumlu burç (en fazla 18 kelime)"}}
  ],
  "full_narration": "Tüm anlatım (TTS yedek)",
  "lucky_number": "1-99 arası",
  "lucky_color": "Renk (Türkçe)",
  "compatible_sign": "Uyumlu burç (12'den biri)",
  "theme": "Kısa tema (3-5 kelime)",
  "description": "YouTube açıklaması (200-300 karakter)",
  "tags": ["burç", "{tr_lower(info['name'])}", "günlük", "astroloji", "shorts"],
  "hashtags": ["#{tr_lower(info['name'])}burcu", "#günlükburç", "#astroloji", "#shorts"]
}}"""


def get_visual_queries(topic_key: str, content: dict = None) -> list:
    info = get_sign(topic_key)
    return info["visual_queries"] + [
        f"zodiac {info['en_name']} mystical",
        "astrology stars cosmic",
    ]


def get_theme_colors(topic_key: str, content: dict = None) -> dict:
    info = get_sign(topic_key)
    return {
        "accent_color": info["color"],
        "background_color": info["bg"],
    }


def get_intro_text(topic_key: str, content: dict = None) -> str:
    info = get_sign(topic_key)
    return f"{info['name']} burcu günlük yorum"


def get_outro_text(topic_key: str, content: dict = None) -> str:
    return "Abone ol · Her gün yeni burç yorumu"


def get_lucky_card(topic_key: str, content: dict) -> Optional[dict]:
    """Burç için 3 sütunlu alt kart."""
    return {
        "type": "triple",
        "col1": ("ŞANSLI SAYI", content.get("lucky_number", "")),
        "col2": ("ŞANSLI RENK", content.get("lucky_color", "")),
        "col3": ("UYUMLU BURÇ", content.get("compatible_sign", "")),
    }


def format_title(topic_key: str, content: dict) -> str:
    """YouTube başlığı (max 100). Burç adı yoksa başa eklenir — arama
    ("koç burcu") başlıktaki burç adına göre eşleşir."""
    title = (content.get("title") or "").strip()
    info = get_sign(topic_key)
    if info["name"] not in title:
        title = f"{info['name']} {info['symbol']} {title}".strip()
    return title[:100]


def format_description(topic_key: str, content: dict) -> str:
    """YouTube açıklaması — hashtagler dahil."""
    desc = content.get("description", "")
    hashtags = content.get("hashtags", [])
    if hashtags:
        desc = desc + "\n\n" + " ".join(hashtags[:15])
    return desc


def get_tags(topic_key: str, content: dict) -> list:
    info = get_sign(topic_key)
    base_tags = content.get("tags", [])
    extra_tags = [
        "burç", "günlükburç", "astroloji", "shorts", "keşfet",
        tr_lower(info["name"]), f"{tr_lower(info['name'])}burcu",
    ]
    return list(dict.fromkeys(base_tags + extra_tags))[:15]
