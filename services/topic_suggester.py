"""
Smart Topic Generator
Bir kanal için yaratıcı, özgün konu önerir.
Hazır kategorilere bağlı kalmaz — her seferinde Claude'dan farklı,
duygusal derinliği olan bir tema ister.

Önceki temaları okur, onlardan kaçınmasını söyler.
"""

import json
import logging
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))


def _used_themes_for_channel(channel_id: str) -> list:
    """Bir kanalın son üretilmiş tüm temalarını çıkarır."""
    history_file = DATA_DIR / channel_id / "history.json"
    themes_file = DATA_DIR / channel_id / "used_themes.json"

    themes = []

    # used_themes.json'dan
    if themes_file.exists():
        try:
            data = json.loads(themes_file.read_text(encoding="utf-8"))
            for topic_themes in data.values():
                for t in topic_themes:
                    if isinstance(t, dict) and t.get("theme"):
                        themes.append(t["theme"])
        except Exception:
            pass

    # history.json'dan başlık ve topic_label da temadır
    if history_file.exists():
        try:
            data = json.loads(history_file.read_text(encoding="utf-8"))
            for entry in data[-50:]:
                t = entry.get("topic_label") or entry.get("title", "")
                if t:
                    themes.append(t)
        except Exception:
            pass

    # Tekrarsız son 30
    seen = set()
    unique = []
    for t in reversed(themes):
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
        if len(unique) >= 30:
            break
    return unique


def suggest_topic_for_motivation(channel_id: str = "sozbahcesi",
                                 time_of_day: str = "sabah") -> dict:
    """Motivasyon kanalı için Claude'dan yaratıcı bir konu ister.

    time_of_day: 'sabah' | 'akşam' — günün vaktine uygun ton.

    Returns:
        {"slug": "yalnizlik-icinde-kalabalik",
         "topic": "Yalnızlığın içinde kalabalık olmak"}
    """
    used = _used_themes_for_channel(channel_id)
    used_str = ", ".join(used[:20]) if used else "yok"

    time_hint = {
        "sabah": "Sabah enerjisi — gün başlangıcı, umut, niyet, yeniden doğuş.",
        "akşam": "Akşam refleksi — gün sonu, içe dönüş, sakinlik, sorgulama.",
    }.get(time_of_day, "")

    prompt = f"""Sen bir motivasyon ve yaşam koçluğu içerik küratörüsün.
60 saniyelik bir YouTube Shorts videosu için **özgün, derin, vurucu**
bir konu öner.

Tarih: {datetime.now().strftime("%d %B %Y")}
Zaman: {time_hint}

Klasik motivasyon klişelerinden kaçın ("hayallerinin peşinden git",
"asla pes etme" gibi sıkıcı kategoriler yerine).

İnsanların **yüreklerini titretecek**, **düşünmelerini sağlayacak**,
sıradan görünen ama derin bir gerçeği ortaya koyan konular seç.
Örnek alanlar: ilişki dinamikleri, varoluşsal sorular, hayatın
çelişkileri, kabullenme, içsel sesler, küçük detaylar...

Önceden işlenmiş temalar (bunları TEKRARLAMA):
{used_str}

Sadece JSON döndür:
{{
  "topic": "Konu başlığı (3-7 kelime, çarpıcı, akılda kalıcı)",
  "rationale": "Neden bu konu? (1 cümle, neden insanlara dokunur)"
}}

ÖRNEKLER (formatı göster, içerik kullanma):
- "Sevdiğin biri seni unutursa"
- "Hatırlanmak istemenin sızısı"
- "Geç fark edilen şefkatler"
- "İçinde kaybolan çocukluğun"
- "Veda etmeden gidenler için"

Türkçe, samimi, içten ol."""

    from services.content import call_llm_with_fallback, parse_llm_json
    raw, provider = call_llm_with_fallback(prompt)
    data = parse_llm_json(raw)

    topic = (data.get("topic") or "").strip().strip('"\'')
    if not topic:
        raise RuntimeError("LLM bir konu önermedi")

    # Slug üret
    slug = re.sub(r"[^a-z0-9çğıöşü\s-]", "", topic.lower())
    slug = re.sub(r"\s+", "-", slug.strip())[:40] or "topic"

    log.info(f"[{provider}] Smart topic: {topic} (slug: {slug})")
    return {
        "slug": slug,
        "topic": topic,
        "rationale": data.get("rationale", ""),
        "provider": provider,
    }
