"""
Yedek burç üretimi (GitHub Actions)
───────────────────────────────────
Her sabah Railway'in günlük burç videolarını YouTube'a yükleyip
yüklemediğine bakar. Bugünün burçlarından hiçbiri kanalda yoksa (Railway
çökmüş ya da üretim başarısız) videoları burada üretip YouTube'a
yükler ve Telegram'a bildirir.

Railway'deki volume'e erişim olmadığı için: astrolog klipleri (HeyGen)
ve Instagram paylaşımı bu modda kapalıdır; YouTube'a hemen (planlamasız)
yüklenir.

Kullanım:  python scripts/fallback_burc.py [--check] [--force]
  --check: sadece kontrol eder, GITHUB_OUTPUT'a needed=true/false yazar
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Yedek modda volume yok: sunucu klibi ve Instagram kapalı
os.environ.setdefault("ZODIAC_PRESENTER", "0")
os.environ.setdefault("INSTAGRAM_ENABLED", "0")
os.environ.setdefault("INSTAGRAM_CHANNELS", "-")

import bootstrap  # noqa: E402

bootstrap.setup_all()
log = logging.getLogger("fallback")

# Kanal ayarları (ses vb.) Railway'deki kanalın kopyasından gelir
_channels = Path(os.environ.get("DATA_DIR", "data")) / "channels.json"
if not _channels.exists():
    _channels.write_text((ROOT / "scripts" / "fallback_channels.json")
                         .read_text(encoding="utf-8"), encoding="utf-8")

CHANNEL = os.environ.get("FALLBACK_CHANNEL", "burc")


def todays_uploads(sign_names: list) -> list:
    """Kanalın bugün (İstanbul) yüklediği, bugünün burçlarına ait videolar."""
    from services.youtube import get_youtube_service
    from services.tr_locale import now_local
    yt = get_youtube_service(channel_id=CHANNEL)
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = yt.playlistItems().list(part="snippet", playlistId=uploads,
                                    maxResults=25).execute().get("items", [])
    today = now_local().date()
    tz = now_local().tzinfo
    found = []
    for it in items:
        sn = it["snippet"]
        ts = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        title = sn.get("title", "")
        if (ts.astimezone(tz).date() == today
                and any(n in title for n in sign_names)):
            found.append(title)
    return found


def _set_output(need: bool) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"needed={'true' if need else 'false'}\n")


def main():
    force = "--force" in sys.argv
    check_only = "--check" in sys.argv
    from zodiac import get_todays_group, get_sign
    group = get_todays_group()
    names = [get_sign(k)["name"] for k in group]
    log.info(f"Bugünün burçları: {', '.join(names)}")

    found = todays_uploads(names)
    need = force or not found
    if found:
        log.info(f"✅ Railway bugün {len(found)} video yüklemiş: {found}")
    if not need:
        log.info("Yedek üretime gerek yok")
    else:
        log.warning(f"⚠️ Yedek üretim gerekli (force={force})")
    if check_only:
        _set_output(need)
        return 0
    if not need:
        return 0

    # Ağır modüller (moviepy vb.) sadece üretimde yüklenir
    from telegram_bot import send as tg_send
    import pipeline
    tg_send(f"🛟 <b>Yedek üretim</b> (GitHub Actions)\nRailway bugünün burç "
            f"videolarını yüklemedi.\n🔮 {', '.join(names)} şimdi üretiliyor "
            f"(astrologsuz, Instagram'sız).")
    res = pipeline.produce_signs(group, upload=True, source="fallback",
                                 channel_id=CHANNEL)
    ok, bad = len(res["success"]), len(res["failed"])
    links = "\n".join(r.get("youtube_url", "") for r in res["success"]
                      if r.get("youtube_url"))
    tg_send(f"🛟 Yedek üretim bitti: {ok}/{len(group)} başarılı"
            + (f", {bad} başarısız" if bad else "")
            + (f"\n{links}" if links else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
