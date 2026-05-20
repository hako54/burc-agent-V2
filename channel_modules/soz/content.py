"""
Söz İçerik Modülü
─────────────────
- LLM ile söz üretimi + mood etiketleri
- Theme matcher (mood'a göre tema seçimi)
- Pipeline ile uyumlu format/title/tag fonksiyonları
"""

import random
import logging
from datetime import datetime
from typing import Optional, Tuple, List

from .config import THEMES, HEYGEN_CONFIG, all_mood_tags

log = logging.getLogger(__name__)


# ── Topic listesi (dashboard kart grid'i için) ─────────────────────

def get_topics() -> list:
    """Dashboard'da gösterilecek topic listesi.
    Her tema bir topic + bir de 'auto' (otomatik tema seçimi)."""
    topics = [
        {
            "key": "auto",
            "name": "Otomatik Tema",
            "icon": "✨",
            "emoji": "✨",
            "subtitle": "Söz anlamına göre tema seçilsin",
            "meta": "Akıllı",
            "color": "#c084fc",
        }
    ]
    for theme_id, theme in THEMES.items():
        topics.append({
            "key": theme_id,
            "name": theme["name"],
            "icon": theme["icon"],
            "emoji": theme["icon"],
            "subtitle": theme["description"][:60],
            "meta": "",
            "color": "#c084fc",
        })
    return topics


# ── Prompt builder ─────────────────────────────────────────────────

def build_prompt(topic_key: str, custom_topic: Optional[str] = None,
                 used_themes: Optional[List[str]] = None) -> str:
    """LLM için söz üretim prompt'u."""
    today = datetime.now().strftime("%d %B %Y")
    used = ", ".join(used_themes[-15:]) if used_themes else "yok"

    # Topic'e göre yönlendirme
    theme_hint = ""
    if topic_key and topic_key != "auto" and topic_key in THEMES:
        theme = THEMES[topic_key]
        theme_hint = (
            f"\n\nİsteğe bağlı yönlendirme: '{theme['name']}' temasıyla "
            f"uyumlu bir söz üret. Bu temanın mood'ları: "
            f"{', '.join(theme['moods'][:5])}"
        )
    elif custom_topic:
        theme_hint = f"\n\nÖzel konu/yönlendirme: {custom_topic}"

    moods_list = ", ".join(all_mood_tags())

    return f"""Sen derin düşünceli, sıcak ve şiirsel bir Türk söz yazarısın.
YouTube Shorts için 20-30 saniyelik kısa ama özlü bir söz yazıyorsun.

Tarih: {today}{theme_hint}

İçten, özgün ve etkileyici bir söz üret. Şu özellikleri taşısın:
- 2-3 cümle, 25-50 kelime arası (kısa olmasi şart, HeyGen 30sn okuyacak)
- Tek bir derin fikre odaklan, dağılma
- Klişeden uzak — "inan kendine", "başarabilirsin", "her şey yoluna girer"
  gibi BAYAT ifadeler KESİNLİKLE YASAK
- Şiirsel ama anlaşılır dil
- "Sen" zamiri kullanma — herkese hitap eden, evrensel olsun
- Okunduğunda duraklatıp düşündürtecek bir derinlik olsun
- Aforizma/maxim formatında olabilir

Son üretilen sözler (BUNLARI TEKRARLAMA): {used}

══════════════════════════════════════════════════════════════════
TÜRKÇE İMLA — KESİNLİKLE UYGULA
══════════════════════════════════════════════════════════════════
1. "de/da" bağlacı AYRI yazılır ("hayatta da", "bir gün de")
2. "bir şey" ayrı, "hiçbir" birleşik, "hâlâ" şapkalı
3. Cümle noktayla biter, virgül sonrası boşluk
4. yalnış→yanlış, herkez→herkes, yanlız→yalnız, çünki→çünkü

══════════════════════════════════════════════════════════════════
MOOD ETİKETLERİ — sözün ruh halini etiketle (2-4 adet seç)
══════════════════════════════════════════════════════════════════
Aşağıdaki listeden 2-4 etiket seç:
{moods_list}

Eğer YUKARIDAKİ listede sözün moodunu doğru yansıtan etiket YOKSA,
"new_mood_needed": true yap ve "suggested_theme" alanına yeni tema
önerisini İngilizce sahne tarifiyle yaz (Flux/HeyGen üretebilsin).

══════════════════════════════════════════════════════════════════
SADECE JSON döndür (başka hiçbir metin yok, markdown yok):
{{
  "soz": "Söz metni — tek satırda, HeyGen okuyacak (noktalama doğru)",
  "title": "YouTube başlığı (40-70 karakter, çarpıcı, emojisiz)",
  "theme": "2-3 kelimelik tema özeti",
  "moods": ["etiket1", "etiket2"],
  "new_mood_needed": false,
  "suggested_theme": {{
    "name": "yeni_tema_adi_snake_case",
    "scene_prompt_en": "Same blonde woman with long wavy hair, light blue eyes, ... [yeni sahne]"
  }},
  "description": "YouTube açıklaması (100-200 karakter)",
  "tags": ["söz", "özlü söz", "shorts", "günlük", "düşünce"],
  "hashtags": [
    "// 12-18 hashtag üret — YouTube Shorts algoritmasını besleyecek bolca",
    "// İlk 3-5: söz konusuna özel (sözün ana fikriyle ilgili)",
    "// Sonraki 5-7: trend/popüler (günlük arananlar)",
    "// Son 3-5: kategori (#shorts, #özlüsözler, #motivasyon vs.)",
    "// Türkçe ve İngilizce karışık olabilir, Türkçe ağırlıklı",
    "// ÖRNEK: #söz #hayat #anlam #içgüdü #yaşamfelsefesi #huzur #motivasyon",
    "//         #özlüsözler #ilham #shorts #shortsfeed #hayatdersleri #bilgelik #aforizma"
  ]
}}

ÖNEMLI: full_narration alanı yok — pipeline.py için 'soz' alanı,
'full_narration'a kopyalanacak. JSON formatına UYUM ŞART.
hashtags MUTLAKA 12-18 adet olsun (algoritma için kritik)."""


# ── Theme matcher ──────────────────────────────────────────────────

def match_theme(moods: List[str], min_score: int = 1) -> Tuple[Optional[str], int]:
    """Mood etiketlerine göre en uygun temayı bul.

    Args:
        moods: LLM'in seçtiği mood etiketleri
        min_score: en az kaç mood eşleşmesi yeterli (varsayılan 1)

    Dönüş:
        (theme_id, score) eşleşme varsa
        (None, 0) hiç eşleşme yoksa
    """
    if not moods:
        return None, 0

    moods_set = set(str(m).lower().strip() for m in moods if m)
    if not moods_set:
        return None, 0

    best_theme_id = None
    best_score = 0

    for theme_id, theme in THEMES.items():
        theme_moods = set(theme["moods"])
        overlap = len(moods_set & theme_moods)
        if overlap > best_score:
            best_score = overlap
            best_theme_id = theme_id

    if best_score < min_score:
        return None, 0

    return best_theme_id, best_score


def pick_look_id(theme_id: str) -> str:
    """Bir temadan rastgele bir look_id seç (varyasyon için)."""
    if theme_id not in THEMES:
        # Fallback: stüdyo (orijinal Lina)
        return THEMES["studyo"]["look_ids"][0]
    look_ids = THEMES[theme_id]["look_ids"]
    return random.choice(look_ids)


def get_theme_info(theme_id: str) -> dict:
    """Tema metadata'sı."""
    return THEMES.get(theme_id, THEMES["studyo"])


# ── Hashtag pool'ları (YouTube algoritması için bolca) ───────────────

# Her temaya özel hashtag'ler (tema seçildiğinde otomatik eklenir)
_THEME_HASHTAGS = {
    "akdeniz_kafe": [
        "#sohbet", "#paylaşım", "#dostluk", "#samimiyet", "#muhabbet",
        "#yakınlık", "#bağ", "#anlam",
    ],
    "mykonos_sahili": [
        "#özgürlük", "#deniz", "#yaz", "#hayal", "#tatil",
        "#summer", "#sea", "#beach", "#ufuk",
    ],
    "sonbahar_gol": [
        "#huzur", "#sukunet", "#tefekkür", "#içdünya", "#sonbahar",
        "#sessizlik", "#derinlik", "#kabul", "#meditasyon",
    ],
    "sonbahar_sokak": [
        "#cesaret", "#kararlılık", "#güç", "#azim", "#sebat",
        "#irade", "#başarı", "#mücadele", "#dik",
    ],
    "lavanta_tarlasi": [
        "#şükür", "#doğa", "#güzellik", "#yaşam", "#minnet",
        "#mutluluk", "#küçükşeyler", "#sevgi", "#ferah",
    ],
    "yaz_sokak": [
        "#umut", "#yenilenme", "#enerji", "#başlangıç", "#yaz",
        "#neşe", "#canlılık", "#sevinç", "#tazelik",
    ],
    "studyo": [
        "#günlük", "#samimi", "#modern", "#sade", "#kişisel",
    ],
}

# Her video'ya eklenecek genel/trend hashtag'ler
_GENERAL_HASHTAGS = [
    "#shorts", "#shortsfeed", "#shortsvideo", "#youtubeshorts",
    "#söz", "#özlüsözler", "#sözler", "#aforizma",
    "#motivasyon", "#ilham", "#hayat", "#yaşam",
    "#düşünce", "#felsefe", "#bilgelik", "#hikmet",
    "#hayatdersleri", "#hayatfelsefesi", "#günlüksöz",
]


def _build_hashtag_set(topic_key: str, content: dict, max_count: int = 30) -> list:
    """LLM hashtag'leri + tema hashtag'leri + genel trend hashtag'leri birleştir.

    YouTube açıklamaları için bolca hashtag (algoritma beslemesi).
    """
    seen = set()
    result = []

    def _add(tag):
        if not tag:
            return
        t = tag.strip()
        if not t.startswith("#"):
            t = "#" + t
        # Boşluk veya geçersiz karakterleri at
        t = t.replace(" ", "").replace("\n", "").replace(",", "")
        if len(t) < 2 or len(t) > 50:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        result.append(t)

    # 1. LLM'in ürettiği hashtag'ler (en yüksek öncelik)
    for tag in (content.get("hashtags") or [])[:20]:
        _add(tag)

    # 2. Tema-spesifik hashtag'ler
    theme_id = (content.get("heygen_theme") or topic_key or "").lower()
    if theme_id in _THEME_HASHTAGS:
        for tag in _THEME_HASHTAGS[theme_id]:
            _add(tag)

    # 3. Mood etiketlerinden hashtag türet (örn. "huzur" → "#huzur")
    for mood in content.get("moods", [])[:6]:
        if mood and "_" not in mood:  # snake_case olanları atla
            _add("#" + mood)

    # 4. Genel trend hashtag'ler (en son, doldurmak için)
    for tag in _GENERAL_HASHTAGS:
        if len(result) >= max_count:
            break
        _add(tag)

    return result[:max_count]


# ── Pipeline interface — format/title/tags ─────────────────────────

def format_title(topic_key: str, content: dict) -> str:
    """YouTube başlığı — #Shorts etiketiyle."""
    title = (content.get("title") or "Günün Sözü")[:88]
    # Başlıkta 1-2 trend hashtag (alt sınır 70 char title, sonra hashtag)
    if "#shorts" not in title.lower():
        title = title + " #Shorts #söz"
    return title[:100]


def format_description(topic_key: str, content: dict) -> str:
    """YouTube açıklaması — söz metni + zengin hashtag seti.

    Yapı:
      - Söz metni (büyük tırnak içinde)
      - Kısa açıklama
      - Boş satır
      - 20-30 hashtag (algoritma için)
      - Alt satırlar: kanal CTA
    """
    soz = (content.get("soz") or "").strip()
    desc = (content.get("description") or "").strip()
    hashtags = _build_hashtag_set(topic_key, content, max_count=30)

    parts = []
    if soz:
        parts.append(f"\"{soz}\"")
        parts.append("")
    if desc:
        parts.append(desc)
        parts.append("")
    # Hashtag bloğu — YouTube açıklamalarda 60 satıra kadar görünür,
    # algoritma için ilk 3-5 hashtag önemli, kalanı arama için
    if hashtags:
        parts.append(" ".join(hashtags))
        parts.append("")
    parts.append("─── 💭 Her gün yeni söz ───")
    parts.append("Abone ol ve bildirimleri aç!")

    return "\n".join(parts)


def get_tags(topic_key: str, content: dict) -> list:
    """YouTube video tag'leri (hashtag'den farklı — video meta tag'leri).

    YouTube tag'leri 500 karakteri geçmemeli toplamda.
    """
    base = content.get("tags") or []
    # Tema etiketleri
    theme_id = (content.get("heygen_theme") or topic_key or "").lower()
    theme_extras = []
    if theme_id in _THEME_HASHTAGS:
        # Hashtag'lerden # çıkar → plain tag
        theme_extras = [
            t.lstrip("#") for t in _THEME_HASHTAGS[theme_id][:5]
        ]

    extra = [
        "söz", "özlü söz", "özlü sözler", "günlük söz",
        "shorts", "youtube shorts", "shorts feed",
        "motivasyon", "ilham", "hayat", "yaşam",
        "düşünce", "felsefe", "bilgelik", "aforizma",
        "hayat dersleri", "günlük motivasyon",
    ]
    all_tags = list(dict.fromkeys(base + theme_extras + extra))

    # YouTube limit: 500 char total. ~20-25 tag güvenli sayı.
    return all_tags[:20]


# ── Pipeline uyum şim'leri (kullanılmıyor ama interface gerek) ─────

def get_visual_queries(topic_key: str, content: dict = None) -> list:
    """HeyGen kendi görseli ürettiği için bu pipeline'da kullanılmaz."""
    return []


def get_theme_colors(topic_key: str, content: dict = None) -> dict:
    return {
        "accent_color": "#c084fc",
        "background_color": "#15081f",
    }


def get_intro_text(topic_key: str, content: dict = None) -> str:
    if content:
        return content.get("theme", "Söz")
    return "Söz"


def get_outro_text(topic_key: str, content: dict = None) -> str:
    return "Abone ol · Her gün yeni söz"


def get_lucky_card(topic_key: str, content: dict) -> Optional[dict]:
    """Söz kanalında lucky card yok."""
    return None
