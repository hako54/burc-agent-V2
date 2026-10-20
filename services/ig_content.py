"""
Instagram'a özel içerik: manifest ve numeroloji Reels'leri
──────────────────────────────────────────────────────────
Sadece Instagram'a gider (YouTube'a değil). Claude metni yazar, yazılı
Reels (fon müzikli) üretilir ve Instagram kuyruğuna konur.

Zamanlama (Railway değişkeni):
  IG_CONTENT_SCHEDULE — "manifest@08:30,numeroloji@19:30" (varsayılan).
                        Boş bırakılırsa ("-") otomatik üretim kapalı.
"""

import os
import random
import logging
from datetime import date
from pathlib import Path

from services.content import call_llm_with_fallback, parse_llm_json
from services.tr_locale import tr_date, tr_upper, now_local

log = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))

MANIFEST_THEMES = [
    "bolluk ve bereket", "para ve maddi akış", "aşk ve sevgi",
    "sağlık ve şifa", "öz sevgi ve özgüven", "huzur ve iç denge",
    "başarı ve kariyer", "koruma ve arınma", "şükür", "yeni başlangıçlar",
]

_COMMON_RULES = """TÜRKÇE İMLA: "de/da", "ki", "mi" ayrı; "bir şey" ayrı; yanlış yazım yok.
Her cümle kısa, akıcı, Instagram'da ekranda okunacak (en fazla 9 kelime).
Tüm metinleri NORMAL yazımla yaz (büyük harfe çevirmeyi sistem yapar).
Sadece JSON döndür."""


def _manifest_prompt(theme: str) -> str:
    return f"""Instagram Reels için "{theme}" temalı bir MANİFEST (olumlama) yaz.
Ekranda müzik eşliğinde tek tek belirecek 5 cümle. Şimdiki zaman, güçlü,
duygusal ve inandırıcı olsun. Örnek tarz: "Bolluk ve bereket hayatıma
oluk oluk akıyor." / "Evren bana her gün yeni kapılar açıyor."
Klişe ve tekrar yok. Bugün: {tr_date()}.

{_COMMON_RULES}
{{
  "title": "Kısa başlık (2-4 kelime, NORMAL yazımla, BÜYÜK HARF KULLANMA; örn. 'Bolluk Manifesti ✨')",
  "lines": ["5 olumlama cümlesi"],
  "caption": "Instagram açıklaması (2-3 cümle, samimi; 'Kaydet ve her sabah 3 kez tekrar et' gibi bir çağrı içersin)",
  "hashtags": ["#manifest", "#olumlama", "... toplam 12-18 Türkçe/İngilizce etiket"],
  "visual_queries": ["İngilizce 3 görsel arama sorgusu (ör. 'golden light abundance', 'sunrise flowers glow')"],
  "accent_color": "#hex (temaya uygun parlak renk)"
}}"""


def universal_day_number(d: date) -> int:
    """Numerolojide evrensel gün sayısı (11/22 usta sayıları korunur)."""
    n = sum(int(c) for c in d.strftime("%Y%m%d"))
    while n > 9 and n not in (11, 22):
        n = sum(int(c) for c in str(n))
    return n


def _numerology_prompt(num: int) -> str:
    return f"""Instagram Reels için NUMEROLOJİ içeriği yaz. Bugün {tr_date()};
numerolojide günün (evrensel gün) sayısı: {num}.
Ekranda müzik eşliğinde tek tek belirecek 5 cümle: sayının bugünkü
enerjisi, neye iyi geldiği, nelerden kaçınmalı, kısa bir tavsiye ve
merak uyandıran kapanış. Somut, akıcı, abartısız.

{_COMMON_RULES}
{{
  "title": "Günün Sayısı: {num} 🔢",
  "lines": ["5 cümle"],
  "caption": "Instagram açıklaması (2-3 cümle; 'Doğum tarihini yorumlara yaz, kişisel sayını söyleyelim' gibi bir çağrı)",
  "hashtags": ["#numeroloji", "... toplam 12-18 etiket"],
  "visual_queries": ["İngilizce 3 görsel arama sorgusu (ör. 'sacred geometry gold', 'night sky numbers mystical')"],
  "accent_color": "#hex"
}}"""


def _event_prompt(ev: dict) -> str:
    from services.tr_locale import tr_date as _trd
    when = ev["when"].astimezone(now_local().tzinfo)
    return f"""Instagram Reels için GÖK OLAYI içeriği yaz.
Olay: {ev['title']} ({ev['emoji']})
Zaman: {_trd(when)} saat {when.strftime('%H:%M')} (Türkiye saati)
Bu video olaydan ÖNCE yayınlanacak; izleyiciyi hazırlasın.

Ekranda müzik eşliğinde tek tek belirecek 5 cümle:
1) Olay ne ve ne zaman (somut, merak uyandıran),
2) Hangi alanları etkiler (aşk, iş, iletişim…),
3) En çok etkilenecek burçlar (2-3 burç adı),
4) Ne yapmalı / ne yapmamalı,
5) Kısa, güçlü bir kapanış.
Abartısız, korkutmayan, akıcı Türkçe.

{_COMMON_RULES}
{{
  "title": "Kısa başlık (NORMAL yazımla, emoji ile; örn. 'Yarın Dolunay Boğa'da 🌕')",
  "lines": ["5 cümle"],
  "caption": "Instagram açıklaması (2-3 cümle; 'Burcunu yorumlara yaz, seni nasıl etkileyeceğini söyleyelim' gibi bir çağrı)",
  "hashtags": ["#astroloji", "... toplam 12-18 etiket, olaya özel olanlar dahil"],
  "visual_queries": ["İngilizce 3 görsel arama sorgusu (ör. 'full moon night sky', 'cosmic stars nebula')"],
  "accent_color": "#hex"
}}"""


def generate(kind: str, theme: str = None, event: dict = None) -> dict:
    """LLM ile içerik üretir: title, lines, caption, hashtags, ..."""
    if kind == "manifest":
        theme = theme or random.choice(MANIFEST_THEMES)
        prompt = _manifest_prompt(theme)
    elif kind == "gokolayi":
        if not event:
            from services import astro_events
            event = (astro_events.upcoming(days=14) or [None])[0]
            if not event:
                raise RuntimeError("Yakında gök olayı yok")
        theme = event["title"]
        prompt = _event_prompt(event)
    elif kind == "numeroloji":
        prompt = _numerology_prompt(universal_day_number(now_local().date()))
    else:
        raise ValueError(f"Bilinmeyen Instagram içerik türü: {kind}")
    raw, provider = call_llm_with_fallback(prompt, max_tokens=1200)
    data = parse_llm_json(raw)
    if not data.get("lines"):
        raise RuntimeError("LLM cümle üretmedi")
    # Ekranda görünecek metinlerin son imla kontrolü
    from services.tr_spell import fix_turkish
    fixed = fix_turkish([data.get("title", "")] + list(data["lines"]))
    data["title"], data["lines"] = fixed[0], fixed[1:]
    data["kind"], data["theme"], data["provider"] = kind, theme, provider
    return data


def produce(kind: str, theme: str = None, publish_now: bool = True,
            event: dict = None) -> dict:
    """Üret → render → Instagram kuyruğu. publish_now=True ise hemen
    kuyruğu işletir (zamanı şimdi)."""
    from services import instagram
    from services.ig_reels import render_text_reel

    data = generate(kind, theme, event=event)
    stamp = now_local().strftime("%Y%m%d_%H%M%S")
    out = str(OUTPUT_DIR / f"ig_{kind}_{stamp}.mp4")
    render_text_reel(
        tr_upper(data.get("title") or kind),
        data["lines"],
        data.get("visual_queries") or [],
        out,
        accent_hex=data.get("accent_color") or "#d4af37",
        outro={"manifest": "Kaydet 🔖 Her sabah tekrar et ✨",
               "gokolayi": "Burcunu yorumlara yaz 💬 Kaydet 🔖"}.get(
                   kind, "Doğum tarihini yorumlara yaz 💬"),
        music_hint="bolluk" if kind == "manifest" else "gece",
    )
    if kind == "manifest":
        data["caption"] = (data.get("caption", "").rstrip() +
                           "\n\nAdını yorumlara yaz, isminin sırrını cevap "
                           "olarak yazayım ✨")
    caption = instagram.build_caption(
        "\n".join(data["lines"][:1]) if kind == "manifest"
        else data.get("title", ""),
        data.get("caption", ""), data.get("hashtags", []))
    item = instagram.enqueue("ig", kind, out, caption)
    if publish_now:
        instagram.process_queue()
    return {"video": out, "queue_id": item["id"], **data}


def schedule() -> list:
    """[(kind, 'HH:MM'), ...] — IG_CONTENT_SCHEDULE'dan."""
    raw = os.environ.get("IG_CONTENT_SCHEDULE",
                         "manifest@08:30,numeroloji@19:30").strip()
    if raw in ("", "-", "0", "off"):
        return []
    out = []
    for part in raw.split(","):
        if "@" in part:
            kind, hhmm = part.strip().split("@", 1)
            out.append((kind.strip(), hhmm.strip()))
    return out


def astro_events_job() -> None:
    """Her gün çalışır: YARIN gerçekleşecek gök olayları için Reels
    üretir (günde en fazla 2). IG_ASTRO_EVENTS=0 ise kapalı."""
    from datetime import timedelta
    from services import instagram, astro_events
    if (not instagram.enabled()
            or os.environ.get("IG_ASTRO_EVENTS", "1") in ("0", "false")):
        return
    tomorrow = (now_local() + timedelta(days=1)).date()
    tz = now_local().tzinfo
    evs = [e for e in astro_events.upcoming(days=3)
           if e["when"].astimezone(tz).date() == tomorrow][:2]
    for ev in evs:
        try:
            produce("gokolayi", event=ev)
        except Exception as e:
            log.exception(f"Gök olayı Reels'i başarısız: {ev['title']}")
            try:
                from telegram_bot import send as tg_send
                tg_send(f"⚠️ Gök olayı Reels'i üretilemedi "
                        f"({ev['title']}): {str(e)[:200]}")
            except Exception:
                pass


def scheduled_job(kind: str) -> None:
    from services import instagram
    if not instagram.enabled():
        return
    try:
        produce(kind)
    except Exception as e:
        log.exception(f"Instagram {kind} üretimi başarısız")
        try:
            from telegram_bot import send as tg_send
            tg_send(f"⚠️ Instagram {kind} üretilemedi: {str(e)[:200]}")
        except Exception:
            pass
