"""
Hafta sonu burç listesi videosu
───────────────────────────────
Cumartesi/pazar günlük burç yerine: "En kıskanç 3 burç" gibi bir liste.
Hafta içi videolarındaki astrolog (HeyGen) açılışta konuyu söyler, her
burç kendi stok videosu (Pexels, hareketli) üzerinde astrologun sesiyle
anlatılır, kapanışta astrolog yorum çağrısı yapar. Video hem YouTube
Shorts'a hem Instagram Reels'e gider.

Bu yol başarısız olursa ig_content'teki yazılı liste Reels'ine düşülür.
"""

import os
import logging
from pathlib import Path

from services.content import call_llm_with_fallback, parse_llm_json
from services.tr_locale import tr_date, tr_upper, now_local

log = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))
# Sabit kapanış: HeyGen klibi bir kez üretilip önbellekten kullanılır
# Her burcun sembolünü gösteren stok video aramaları (İngilizce)
SIGN_VISUALS = {
    "koc": "ram mountain", "boga": "bull field", "ikizler": "twins sisters",
    "yengec": "crab beach", "aslan": "lion", "basak": "wheat field woman",
    "terazi": "balance scales", "akrep": "scorpion", "yay": "archer bow arrow",
    "oglak": "mountain goat", "kova": "water pouring", "balik": "fish underwater",
}
OUTRO_LINE = ("Senin burcun listede mi? Yorumlara yaz, arkadaşını etiketle "
              "ve takipte kal!")


def _prompt(topic: str) -> str:
    return f"""Hafta sonu için eğlenceli BURÇ LİSTESİ videosu yaz. Konu: "{topic}".
Bir kadın astrolog seslendirecek; "sen" diliyle, sıcak, esprili, kimseyi
kırmayan bir dil. Gerçekten o özelliğiyle bilinen 3 farklı burç seç.
Bugün: {tr_date()}.

TÜRKÇE İMLA: "de/da", "ki", "mi" ayrı; yanlış yazım yok. NORMAL yazımla yaz.
Sadece JSON döndür:
{{
  "title": "{topic} (emoji ile, en fazla 6 kelime)",
  "hook": "Astrologun açılış cümlesi, en fazla 18 kelime (ör. 'Bugün sana en kıskanç üç burcu söylüyorum, birincisi seni şaşırtacak!')",
  "items": [
    {{"sign": "Burç adı (ör. Akrep)",
      "reason": "Seslendirilecek 1-2 kısa cümle, en fazla 24 kelime, 'Bir numara: Akrep.' gibi başlamasın",
      "video_query": "Bu burcu ve gerekçeyi anlatan İngilizce stok video arama sorgusu (ör. 'woman mysterious glance night city')"}}
  ],
  "caption": "Instagram/YouTube açıklaması (2-3 cümle; 'Burcunu yorumlara yaz, arkadaşını etiketle' çağrısı)",
  "hashtags": ["#burç", "... toplam 12-18 etiket, listedeki burçların etiketleri dahil"],
  "accent_color": "#hex (konuya uygun parlak renk)"
}}"""


def _voice_config() -> dict:
    try:
        import channel_registry
        ch = channel_registry.get_channel("burc") or {}
    except Exception:
        ch = {}
    return {"voice_id": ch.get("voice_id"),
            "stability": ch.get("voice_stability", 0.50),
            "style": ch.get("voice_style", 0.35),
            "speed": ch.get("voice_speed", 0.95)}


def build_content(topic: str) -> dict:
    from zodiac import normalize_sign, get_sign
    from services.images import fetch_video_file
    raw, provider = call_llm_with_fallback(_prompt(topic), max_tokens=1500)
    data = parse_llm_json(raw)
    items = []
    for it in data.get("items", []):
        key = normalize_sign(it.get("sign", ""))
        if key and it.get("reason") and key not in [k for k, _ in items]:
            items.append((key, it))
    if len(items) < 3:
        raise RuntimeError("LLM 3 geçerli burç üretmedi")
    items = items[:3]

    from services.tr_spell import fix_turkish
    fixed = fix_turkish([data.get("title", topic), data.get("hook", "")]
                        + [it["reason"] for _, it in items])
    title, hook, reasons = fixed[0], fixed[1], fixed[2:]

    stamp = now_local().strftime("%Y%m%d_%H%M%S")
    used, segments, videos, queries = set(), [], [], []
    for n, ((key, it), reason) in enumerate(zip(items, reasons), 1):
        sign = get_sign(key)
        segments.append({"section": "liste",
                         "text": f"{n}. {sign['name']} {sign['symbol']}",
                         "narration": reason})
        # Önce burcun sembolü (Boğa → boğa), olmazsa LLM'in önerdiği sahne
        dst = str(OUTPUT_DIR / f"liste_{stamp}_b{n}.mp4")
        path = ""
        for q in (SIGN_VISUALS.get(key), it.get("video_query")):
            if q and not path:
                queries.append(q)
                path = fetch_video_file(q, dst, used)
        videos.append(path)

    content = {
        "title": title, "hook_text": title, "intro_text": hook,
        # Liste başlığı her bölümde üstte (Shorts küçük resmi için)
        "segment_header": tr_upper(title),
        "main_label": "Hafta Sonu Özel", "main_icon": "🔮",
        "intro_subtitle": "Burç listesi", "outro_subtitle": "Takipte kal 🔮",
        "accent_color": data.get("accent_color") or "#d4af37",
        "background_color": "#120a1f",
        "segments": segments, "segment_videos": videos,
        "pexels_queries": queries,
        "caption": data.get("caption", ""),
        "hashtags": data.get("hashtags", []),
        "signs": [get_sign(k) for k, _ in items],
        "topic": topic, "provider": provider,
    }
    from services import presenter
    if presenter.enabled():
        content["presenter"] = True
        content["presenter_outro_text"] = OUTRO_LINE
    return content


def produce(topic: str = None, publish: bool = True) -> dict:
    """Üret → render → YouTube Shorts + Instagram Reels. publish=False:
    sadece önizleme (Telegram'a gönderilir, hiçbir yerde yayınlanmaz)."""
    from services import instagram
    from services.ig_content import _list_topic, _upload_youtube
    from services.video import render_video
    from services.ig_reels import make_daily_cover

    topic = topic or _list_topic()
    content = build_content(topic)
    stamp = now_local().strftime("%Y%m%d_%H%M%S")
    out = str(OUTPUT_DIR / f"burc_liste_{stamp}.mp4")
    render_video(content, out, voice_config=_voice_config())

    cover = make_daily_cover(
        content.get("presenter_frame") or "", tr_upper(content["title"]),
        tr_date(), "  ".join(s["symbol"] for s in content["signs"]),
        content["accent_color"], out.replace(".mp4", "_cover.jpg"),
        label="HAFTA SONU ÖZEL")

    if not publish:
        try:
            from telegram_bot import send_video
            send_video(out, f"👀 Önizleme (yayınlanmadı): {content['title']}")
        except Exception as e:
            log.warning(f"Önizleme Telegram'a gönderilemedi: {e}")
        log.info(f"👀 Hafta sonu listesi önizleme: {out}")
        return {"video": out, "cover": out.replace(".mp4", "_cover.jpg"),
                "topic": topic, "title": content["title"]}

    data = {"title": content["title"], "caption": content["caption"],
            "hashtags": content["hashtags"]}
    yt_url = _upload_youtube(out, data, thumbnail_path=cover)
    caption = instagram.build_caption(
        content["title"], content["caption"], content["hashtags"],
        youtube_url=yt_url or None)
    item = instagram.enqueue("ig", "liste", out, caption, cover_path=cover)
    instagram.process_queue()
    log.info(f"🔮 Hafta sonu listesi hazır: {topic} | YouTube: {yt_url}")
    return {"video": out, "topic": topic, "youtube_url": yt_url,
            "queue_id": item["id"]}
