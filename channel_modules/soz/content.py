"""
Söz İçerik Modülü (Stok video + ElevenLabs TTS pipeline)
─────────────────────────────────────────────────────────
- LLM söz üretir + mood etiketleri
- match_theme mood'a göre tema seçer
- Tema visual_queries → Pexels arama
- ElevenLabs ses + FFmpeg cinematic render
"""

from datetime import datetime
from typing import Optional, Tuple, List

from .config import THEMES, all_mood_tags


# ── Topics (dashboard grid'i için) ────────────────────────────────

def get_topics() -> list:
    """Dashboard'da gösterilecek topic listesi.
    Her tema bir topic + 'auto' (otomatik tema seçimi)."""
    topics = [
        {
            "key": "auto",
            "name": "Otomatik Tema",
            "icon": "✨", "emoji": "✨",
            "subtitle": "Söz mood'una göre tema seçilsin",
            "meta": "Akıllı",
            "color": "#c084fc",
        }
    ]
    for theme_id, theme in THEMES.items():
        topics.append({
            "key": theme_id,
            "name": theme["name"],
            "icon": theme["icon"],
            "emoji": theme["emoji"],
            "subtitle": theme["subtitle"],
            "meta": "",
            "color": theme["color"],
        })
    return topics


# ── Prompt builder ─────────────────────────────────────────────────

def build_prompt(topic_key: str, custom_topic: Optional[str] = None,
                 used_themes: Optional[List[str]] = None) -> str:
    """LLM için söz üretim prompt'u.

    Motivasyon pipeline'a uyumlu format döndürür (5 segment + full_narration).
    """
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
YouTube Shorts için 45-60 saniyelik özlü söz + açılım içeriği hazırlıyorsun.

Tarih: {today}{theme_hint}

İçeriğin yapısı:
- Önce çarpıcı bir söz/aforizma (15-25 kelime)
- Sonra sözün anlamını açıklama, somut örnek, ve içe alma
- Toplam 130-180 kelime, 45-60 saniyelik anlatım

Klişeden uzak — "inan kendine", "başarabilirsin", "her şey yoluna girer"
gibi BAYAT ifadeler KESİNLİKLE YASAK.
Şiirsel ama anlaşılır dil. Tek bir derin fikre odaklı.

Son üretilen sözler (BUNLARI TEKRARLAMA): {used}

══════════════════════════════════════════════════════════════════
TÜRKÇE İMLA — KESİNLİKLE UYGULA
══════════════════════════════════════════════════════════════════
1. "de/da" bağlacı AYRI yazılır ("hayatta da", "bir gün de")
2. "bir şey" ayrı, "hiçbir" birleşik, "hâlâ" şapkalı
3. Cümle noktayla biter, virgül sonrası boşluk
4. yalnış→yanlış, herkez→herkes, yanlız→yalnız, çünki→çünkü
5. Rakamları yazıyla (3→üç)

══════════════════════════════════════════════════════════════════
MOOD ETİKETLERİ — sözün ruh halini etiketle (2-4 adet)
══════════════════════════════════════════════════════════════════
Aşağıdaki listeden 2-4 etiket seç:
{moods_list}

══════════════════════════════════════════════════════════════════
SADECE JSON döndür (başka hiçbir metin yok, markdown yok):
{{
  "title": "Çarpıcı YouTube başlığı (40-70 karakter, emojisiz)",
  "hook": "İlk 3 sn — sözün kendisi, çarpıcı, dikkat çekici",
  "segments": [
    {{"time": "0-5s", "section": "hook",
     "text": "Kısa altyazı (3-5 kelime)",
     "narration": "Sözün kendisi — 1 cümle, vurgulu"}},
    {{"time": "5-20s", "section": "acilim",
     "text": "Kısa altyazı",
     "narration": "Sözün ne dediğini açıkla — 2-3 cümle"}},
    {{"time": "20-35s", "section": "ornek",
     "text": "Kısa altyazı",
     "narration": "Somut bir örnek veya metafor — 2 cümle"}},
    {{"time": "35-50s", "section": "icin",
     "text": "Kısa altyazı",
     "narration": "İçselleştirme — okuyucuya/dinleyiciye dön, 'sen' kullan"}},
    {{"time": "50-60s", "section": "kapanis",
     "text": "Kısa altyazı",
     "narration": "Sözü farklı bir açıyla tekrarla veya genişlet — 1 güçlü cümle"}}
  ],
  "full_narration": "Tüm anlatım akıcı tek metin (130-180 kelime, ses için).",
  "key_message": "Söz'ün KENDISI tek satırda (lucky_card'da gösterilecek, 60-100 karakter)",
  "soz": "Söz'ün KENDISI — sözün aforistik versiyonu (key_message ile aynı olabilir)",
  "theme": "2-3 kelimelik tema özeti",
  "moods": ["etiket1", "etiket2"],
  "description": "YouTube açıklaması (100-200 karakter)",
  "tags": ["söz", "özlü söz", "shorts", "günlük", "düşünce"],
  "hashtags": [
    "// 12-18 hashtag üret — YouTube Shorts algoritması için bolca",
    "// İlk 3-5: söz konusuna özel",
    "// Sonraki 5-7: trend/popüler",
    "// Son 3-5: kategori (#shorts, #özlüsözler vs.)",
    "// ÖRNEK: #söz #hayat #anlam #huzur #motivasyon #özlüsözler",
    "//         #ilham #shorts #shortsfeed #hayatdersleri #bilgelik #aforizma"
  ]
}}

ÖNEMLI:
- full_narration 130-180 kelime, doğal akıcı (ElevenLabs okuyacak)
- segments toplam süresi 45-60 saniye olmalı
- soz alanı KÜÇÜK ve VURGULU olsun (15-25 kelime, key_message ile uyumlu)
- hashtags MUTLAKA 12-18 adet olsun
- JSON formatına UYUM ŞART, başka hiçbir metin yok"""


# ── Theme matcher ──────────────────────────────────────────────────

def match_theme(moods: List[str], min_score: int = 1) -> Tuple[Optional[str], int]:
    """Mood etiketlerine göre en uygun temayı bul.

    Dönüş:
        (theme_id, score) — eşleşme varsa
        (None, 0) — hiç eşleşme yoksa (fallback için)
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


def _resolve_theme(topic_key: str, content: dict = None) -> dict:
    """Topic key veya content'in mood'larından tema bul.

    Pipeline.py soz tipinde 'auto' topic gönderirse content'in moods'unu
    kullanarak en uygun temayı seçeriz.
    """
    if topic_key and topic_key in THEMES and topic_key != "auto":
        return THEMES[topic_key]

    if content:
        moods = content.get("moods") or []
        theme_id, _ = match_theme(moods)
        if theme_id:
            return THEMES[theme_id]

    # Fallback
    return THEMES.get("studyo", list(THEMES.values())[0])


# ── Pipeline interface ─────────────────────────────────────────────

def get_visual_queries(topic_key: str, content: dict = None) -> list:
    """Pexels arama için query'ler — tema'dan."""
    theme = _resolve_theme(topic_key, content)
    queries = list(theme.get("visual_queries", []))
    # Genel fallback'ler
    queries += ["peaceful nature cinematic", "warm aesthetic light"]
    return queries


def get_face_queries(topic_key: str, content: dict = None) -> list:
    """Intro face için kadın yüzü query'leri — tema'dan."""
    theme = _resolve_theme(topic_key, content)
    return list(theme.get("face_queries", []))


def get_theme_colors(topic_key: str, content: dict = None) -> dict:
    theme = _resolve_theme(topic_key, content)
    return {
        "accent_color": theme.get("color", "#c084fc"),
        "background_color": theme.get("bg", "#15081f"),
    }


def get_intro_text(topic_key: str, content: dict = None) -> str:
    """Intro'da gösterilecek metin — tema ismi."""
    theme = _resolve_theme(topic_key, content)
    return theme.get("name", "Günün Sözü")


def get_outro_text(topic_key: str, content: dict = None) -> str:
    return "Abone ol · Her gün yeni söz"


def get_lucky_card(topic_key: str, content: dict) -> Optional[dict]:
    """Söz'ün KENDISI tek satırda kart olarak gösterilir."""
    if not content:
        return None
    # Önce key_message, yoksa soz alanı
    msg = content.get("key_message") or content.get("soz") or ""
    if not msg:
        return None
    return {
        "type": "single",
        "label": "GÜNÜN SÖZÜ",
        "value": msg[:120],
    }


# ── Hashtag pool'ları (YouTube algoritması için bolca) ───────────────

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

_GENERAL_HASHTAGS = [
    "#shorts", "#shortsfeed", "#shortsvideo", "#youtubeshorts",
    "#söz", "#özlüsözler", "#sözler", "#aforizma",
    "#motivasyon", "#ilham", "#hayat", "#yaşam",
    "#düşünce", "#felsefe", "#bilgelik", "#hikmet",
    "#hayatdersleri", "#hayatfelsefesi", "#günlüksöz",
]


def _build_hashtag_set(topic_key: str, content: dict, max_count: int = 30) -> list:
    """LLM hashtag'leri + tema + mood + genel trend → birleşik liste."""
    seen = set()
    result = []

    def _add(tag):
        if not tag:
            return
        t = tag.strip()
        if not t.startswith("#"):
            t = "#" + t
        t = t.replace(" ", "").replace("\n", "").replace(",", "")
        if len(t) < 2 or len(t) > 50:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        result.append(t)

    # 1. LLM hashtag'leri
    for tag in (content.get("hashtags") or [])[:20]:
        _add(tag)

    # 2. Tema hashtag'leri
    theme = _resolve_theme(topic_key, content)
    # Tema id'sini bul
    theme_id = None
    for tid, t in THEMES.items():
        if t.get("name") == theme.get("name"):
            theme_id = tid
            break
    if theme_id and theme_id in _THEME_HASHTAGS:
        for tag in _THEME_HASHTAGS[theme_id]:
            _add(tag)

    # 3. Mood'lardan hashtag türet
    for mood in content.get("moods", [])[:6]:
        if mood and "_" not in mood:
            _add("#" + mood)

    # 4. Genel trend hashtag'ler
    for tag in _GENERAL_HASHTAGS:
        if len(result) >= max_count:
            break
        _add(tag)

    return result[:max_count]


# ── Title / Description / Tags ───────────────────────────────────────

def format_title(topic_key: str, content: dict) -> str:
    """YouTube başlığı + #Shorts."""
    title = (content.get("title") or "Günün Sözü")[:85]
    if "#shorts" not in title.lower():
        title = title + " #Shorts #söz"
    return title[:100]


def format_description(topic_key: str, content: dict) -> str:
    """YouTube açıklaması — söz metni + bolca hashtag."""
    soz = (content.get("soz") or content.get("key_message") or "").strip()
    desc = (content.get("description") or "").strip()
    hashtags = _build_hashtag_set(topic_key, content, max_count=30)

    parts = []
    if soz:
        parts.append(f"\"{soz}\"")
        parts.append("")
    if desc:
        parts.append(desc)
        parts.append("")
    if hashtags:
        parts.append(" ".join(hashtags))
        parts.append("")
    parts.append("─── 💭 Her gün yeni söz ───")
    parts.append("Abone ol ve bildirimleri aç!")

    return "\n".join(parts)


def get_tags(topic_key: str, content: dict) -> list:
    """YouTube video tag'leri (hashtag'lerden farklı, plain text)."""
    base = content.get("tags") or []
    theme = _resolve_theme(topic_key, content)
    # Tema id'sini bul
    theme_id = None
    for tid, t in THEMES.items():
        if t.get("name") == theme.get("name"):
            theme_id = tid
            break

    theme_extras = []
    if theme_id and theme_id in _THEME_HASHTAGS:
        theme_extras = [t.lstrip("#") for t in _THEME_HASHTAGS[theme_id][:5]]

    extra = [
        "söz", "özlü söz", "özlü sözler", "günlük söz",
        "shorts", "youtube shorts", "shorts feed",
        "motivasyon", "ilham", "hayat", "yaşam",
        "düşünce", "felsefe", "bilgelik", "aforizma",
        "hayat dersleri", "günlük motivasyon",
    ]
    all_tags = list(dict.fromkeys(base + theme_extras + extra))
    return all_tags[:20]
