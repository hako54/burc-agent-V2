"""
Motivasyon İçerik Modülü
Kategorili + custom topic desteği.
"""

from datetime import datetime

from services.tr_locale import tr_date
from typing import Optional

from .config import CATEGORIES


def get_topics() -> list:
    """Motivasyon kategorileri — dashboard grid için."""
    topics = []
    for key, info in CATEGORIES.items():
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


def build_prompt(topic_key: str, custom_topic: str = None,
                 used_themes: list = None) -> str:
    today = tr_date()
    used = ", ".join(used_themes[-10:]) if used_themes else "yok"

    if custom_topic:
        topic_desc = f"Özel konu: {custom_topic}"
        topic_hint = custom_topic
    else:
        cat = CATEGORIES.get(topic_key, {})
        topic_desc = f"Kategori: {cat.get('name', 'Motivasyon')}"
        topic_hint = (cat.get('name', 'motivasyon') + " - "
                      + cat.get('subtitle', ''))

    return f"""Sen derin düşünceli, sıcak ve ilham verici bir Türk motivasyon yazarısın.
YouTube Shorts için 60 saniyelik günlük motivasyon içeriği hazırlıyorsun.

Tarih: {today}
{topic_desc}

Bugün için {topic_hint} temalı, samimi ve içten bir motivasyon metni yaz.
Klişelerden kaçın (asla "başarabilirsin", "inan kendine" gibi bayat ifadeler
kullanma). Somut, özgün ve derinliği olan bir mesaj ver.

Son kullanılan temalar (BUNLARI TEKRARLAMA): {used}

══════════════════════════════════════════════════════════════════
TÜRKÇE İMLA KURALLARI — KESİNLİKLE UYGULA
══════════════════════════════════════════════════════════════════
1. "de/da" bağlacı AYRI yazılır ("bugün de", "sen de")
2. "bir şey" ayrı, "hiçbir" birleşik, "hâlâ" şapkalı
3. yalnış→yanlış, herkez→herkes, yanlız→yalnız, çünki→çünkü
4. Her cümle noktayla biter. Virgül+noktadan sonra boşluk
5. Rakamları yazıyla (3→üç)
══════════════════════════════════════════════════════════════════

Sadece JSON döndür:
{{
  "title": "Çarpıcı başlık (max 80 karakter, merak uyandıran, emoji ile)",
  "hook": "İlk 3 sn - dikkat çekici giriş",
  "segments": [
    {{"time": "0-5s", "section": "hook", "text": "Kısa altyazı", "narration": "Soru veya iddia"}},
    {{"time": "5-20s", "section": "gelisme", "text": "Kısa altyazı", "narration": "Ana düşünce - 2-3 cümle"}},
    {{"time": "20-35s", "section": "ornek", "text": "Kısa altyazı", "narration": "Somut örnek veya metafor"}},
    {{"time": "35-50s", "section": "icin", "text": "Kısa altyazı", "narration": "İçselleştirme - sen/siz'e hitap"}},
    {{"time": "50-60s", "section": "kapanis", "text": "Kısa altyazı", "narration": "Güçlü kapanış cümlesi"}}
  ],
  "full_narration": "Tüm metin akıcı (170-210 kelime)",
  "key_message": "Tek cümle - videonun ana mesajı",
  "theme": "Kısa tema (3-5 kelime)",
  "description": "YouTube açıklaması (150-250 karakter)",
  "tags": ["motivasyon", "ilham", "günlük", "düşünce", "shorts"],
  "hashtags": ["#motivasyon", "#günlük", "#ilham", "#shorts", "#düşünce"]
}}

ÖNEMLİ: "sen/siz" zamirini kullan, samimi bağ kur ama "arkadaşım", "canım"
gibi aşırı samimi hitap kullanma."""


def get_visual_queries(topic_key: str, content: dict = None) -> list:
    cat = CATEGORIES.get(topic_key, {})
    if cat.get("visual_queries"):
        return cat["visual_queries"] + [
            "inspiring sunrise mountain", "peaceful nature morning"]
    return ["inspiring nature golden", "motivation sunrise peaceful",
            "peaceful mountain dawn", "success mountain sky"]


def get_theme_colors(topic_key: str, content: dict = None) -> dict:
    cat = CATEGORIES.get(topic_key, {})
    return {
        "accent_color": cat.get("color", "#f59e0b"),
        "background_color": cat.get("bg", "#1f1005"),
    }


def get_intro_text(topic_key: str, content: dict = None) -> str:
    """Motivasyon kanalı için intro — sadece kategori ismi."""
    cat = CATEGORIES.get(topic_key, {})
    name = cat.get("name", "Günün Motivasyonu")
    return name


def get_outro_text(topic_key: str, content: dict = None) -> str:
    return "Abone ol · Her gün yeni ilham"


def get_lucky_card(topic_key: str, content: dict) -> Optional[dict]:
    """Motivasyon için: anahtar mesajı tek satırda göster."""
    key_msg = content.get("key_message", "")
    if not key_msg:
        return None
    return {
        "type": "single",
        "label": "GÜNÜN MESAJI",
        "value": key_msg[:100],
    }


def format_title(topic_key: str, content: dict) -> str:
    """Başlık + #Shorts etiketi (YouTube Shorts olarak algılanması için)."""
    title = content.get("title", "")[:88]  # Shorts için yer bırak
    if "#shorts" not in title.lower():
        title = title + " #Shorts"
    return title[:100]


def format_description(topic_key: str, content: dict) -> str:
    """Açıklamanın başına #Shorts ekleyerek Shorts olarak algılanır."""
    desc = content.get("description", "")
    hashtags = content.get("hashtags", [])
    # En başa #Shorts koy (Shorts algılaması için)
    parts = ["#Shorts", ""]
    if desc:
        parts.append(desc)
    if hashtags:
        # Listede #shorts varsa duplicate olmasın
        clean_tags = [t for t in hashtags[:15]
                      if t.lower() not in ("#shorts", "#short")]
        if clean_tags:
            parts.append("\n" + " ".join(clean_tags))
    return "\n".join(parts)


def get_tags(topic_key: str, content: dict) -> list:
    cat = CATEGORIES.get(topic_key, {})
    base_tags = content.get("tags", [])
    extra_tags = [
        "motivasyon", "ilham", "günlük", "düşünce", "shorts",
        "kişiselgelişim",
    ]
    if cat.get("name"):
        extra_tags.append(cat["name"].lower())
    return list(dict.fromkeys(base_tags + extra_tags))[:15]
