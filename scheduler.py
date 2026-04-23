"""
Scheduler — Günlük Otomatik Üretim

Strateji: Gün aşırı 6 burç rotasyonu (YouTube günlük quota sınırı nedeniyle)
- Çift günler (2, 4, 6...): Koç, Boğa, İkizler, Yengeç, Aslan, Başak
- Tek günler (1, 3, 5...): Terazi, Akrep, Yay, Oğlak, Kova, Balık

Zamanlama:
- 09:00 (BURC_BATCH_TIME) → 6 burç üretilir ve YouTube'a 'private'
                             olarak yüklenir (publishAt=bugün 10:00)
- 10:00 (BURC_PUBLISH_TIME) → YouTube otomatik olarak 'public' yapar

Böylece tek cron job yeterli — YouTube'un kendi scheduling'i devreye girer.
"""

import os
import logging
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from pipeline import produce_signs
from zodiac import get_todays_group, get_sign
from telegram_bot import send as tg_send

log = logging.getLogger(__name__)

TIMEZONE = os.environ.get("TIMEZONE", "Europe/Istanbul")
BURC_TIME = os.environ.get("BURC_BATCH_TIME", "09:00")          # üretim başlar
PUBLISH_TIME = os.environ.get("BURC_PUBLISH_TIME", "10:00")     # YouTube yayın


def _calculate_publish_at_iso() -> str:
    """Bugünün PUBLISH_TIME'ı için ISO 8601 tarih döner.
    Örnek: '2026-04-24T10:00:00+03:00'

    Eğer şu anki saat zaten PUBLISH_TIME'ı geçmişse (nadir, ama render
    30 dk sürer ve geç kalırsa), yarın için planla.
    """
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    try:
        h, m = map(int, PUBLISH_TIME.split(":"))
    except Exception:
        h, m = 10, 0

    publish = now.replace(hour=h, minute=m, second=0, microsecond=0)
    # Eğer render çok uzun sürüp publish saatini kaçırdıysak, yarına kaydır
    if publish <= now + timedelta(minutes=5):
        publish += timedelta(days=1)
    return publish.isoformat()


def _daily_batch_job():
    """09:00'da çalışır: günün grubu için 6 burç üretir ve YouTube'a 10:00
    publishAt ile yükler."""
    log.info("=" * 60)
    today = datetime.now(pytz.timezone(TIMEZONE))
    group = get_todays_group()
    day_type = "ÇİFT" if today.day % 2 == 0 else "TEK"

    log.info(f"🔮 Günlük batch — {today.strftime('%d %B %Y')} ({day_type} gün)")
    log.info(f"   Grup: {', '.join(group)}")

    group_names = ", ".join(get_sign(k)["name"] for k in group)
    tg_send(
        f"🌅 <b>Günlük otomatik üretim</b>\n"
        f"📅 {today.strftime('%d %B %Y')} ({day_type} gün)\n"
        f"🔮 Bugünün burçları: {group_names}\n"
        f"⏰ Yayın saati: {PUBLISH_TIME}"
    )

    publish_at = _calculate_publish_at_iso()
    log.info(f"   YouTube publishAt: {publish_at}")

    try:
        results = produce_signs(
            group, upload=True, source="scheduler",
            scheduled_publish_at=publish_at,
        )
        success_count = len(results["success"])
        fail_count = len(results["failed"])

        msg = (
            f"🏁 <b>Üretim tamamlandı</b>\n"
            f"✅ Başarılı: {success_count}/{len(group)}\n"
            f"❌ Başarısız: {fail_count}\n"
            f"📤 YouTube {PUBLISH_TIME}'da otomatik yayınlayacak"
        )
        if results["failed"]:
            failed_names = [r["sign_key"] for r in results["failed"]]
            msg += f"\n⚠ Başarısız: {', '.join(failed_names)}"
        tg_send(msg)
    except Exception as e:
        log.exception("Batch genel hatası")
        tg_send(f"❌ Batch hatası: {str(e)[:200]}")


def start_scheduler():
    """APScheduler'ı başlatır."""
    tz = pytz.timezone(TIMEZONE)
    scheduler = BackgroundScheduler(timezone=tz)

    try:
        hour, minute = map(int, BURC_TIME.split(":"))
    except Exception:
        log.warning(f"Geçersiz BURC_BATCH_TIME '{BURC_TIME}', 09:00 kullanılıyor")
        hour, minute = 9, 0

    scheduler.add_job(
        _daily_batch_job,
        CronTrigger(hour=hour, minute=minute, timezone=tz),
        id="daily_burc_batch",
        name="Günlük 6 Burç Üretimi",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.start()
    log.info(f"📅 Scheduler başladı: her gün {BURC_TIME} "
             f"({TIMEZONE}), yayın {PUBLISH_TIME}")
    log.info(f"   Çift gün grubu: koc, boga, ikizler, yengec, aslan, basak")
    log.info(f"   Tek gün grubu:  terazi, akrep, yay, oglak, kova, balik")
    return scheduler


if __name__ == "__main__":
    import bootstrap
    import time
    bootstrap.setup_all()
    sched = start_scheduler()
    log.info("Scheduler test modunda. Durdurmak için Ctrl+C.")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
