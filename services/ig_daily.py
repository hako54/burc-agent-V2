"""
Instagram günlük burç derlemesi
───────────────────────────────
Sabah üretilen 6 burç videosunun açılış + hook kesitleri tek bir Reels'te
birleşir; her gün farklı bir kapakla (astrologun o günkü karesi, günün
başlığı, burç sembolleri, o burcun rengi) Instagram'a gider.

IG_BURC_DAILY=0 ise kapalı.
"""

import os
import logging
from pathlib import Path

from services.tr_locale import tr_date, tr_lower, now_local

log = logging.getLogger(__name__)

TITLES = [
    "BUGÜN BURÇLARI NE BEKLİYOR?",
    "BU 6 BURCA ÖZEL MESAJ VAR",
    "YILDIZLAR BUGÜN NE SÖYLÜYOR?",
    "BURCUNA BUGÜN NE OLACAK?",
    "BUGÜN ŞANS KİMDEN YANA?",
    "GÖKYÜZÜ BUGÜN SANA ÖZEL",
    "BU BURÇLAR BUGÜN DİKKAT!",
]


def enabled() -> bool:
    from services import instagram
    return (instagram.enabled()
            and os.environ.get("IG_BURC_DAILY", "1") not in ("0", "false"))


def build_and_queue(results: list, publish_after: str = None) -> dict:
    """produce_signs sonuçlarından derleme + kapak üretip kuyruğa ekler."""
    from services import instagram
    from services.ig_reels import make_compilation, make_daily_cover

    items = [r for r in results
             if r.get("video_path") and os.path.exists(r["video_path"])]
    if not items:
        raise RuntimeError("Derlenecek burç videosu yok")
    day = now_local()
    n = day.toordinal()
    out_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    stamp = day.strftime("%Y%m%d")
    video = str(out_dir / f"ig_burclar_{stamp}.mp4")
    cover = str(out_dir / f"ig_burclar_{stamp}_cover.jpg")

    make_compilation([(r["video_path"], r.get("ig_hook_cut_at"))
                      for r in items], video)

    # Kapak her gün farklı: başlık, astrolog karesi ve renk sırayla döner
    pick = items[n % len(items)]
    frames = [r for r in items if r.get("presenter_frame")
              and os.path.exists(r["presenter_frame"])]
    frame = (frames[n % len(frames)]["presenter_frame"] if frames else "")
    make_daily_cover(frame, TITLES[n % len(TITLES)], tr_date(day),
                     "  ".join(r.get("sign_symbol", "") for r in items),
                     pick.get("accent_color") or "#d4af37", cover)

    names = ", ".join(r.get("sign_name", "") for r in items)
    hashtags = ["#burç", "#burçyorumu", "#günlükburç", "#astroloji"] + [
        f"#{tr_lower(r['sign_name'])}burcu" for r in items
        if r.get("sign_name")]
    caption = instagram.build_caption(
        f"{TITLES[n % len(TITLES)].capitalize()} 🔮 {tr_date(day)}",
        f"Bugün {names} burçları için yıldızların mesajı. "
        f"Tam yorumlar YouTube'da, link profilde 👆",
        hashtags)
    item = instagram.enqueue("burc", f"derleme_{stamp}", video, caption,
                             publish_after=publish_after, cover_path=cover)
    return {"video": video, "cover": cover, "queue_id": item["id"]}
