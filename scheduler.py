"""
Scheduler — Günlük Otomatik Üretim
Her gün belirlenen saatte 12 burcu sırayla üretir.

Railway'de bu modül Flask app ile birlikte çalışır.
"""

import os
import logging
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from pipeline import produce_all_signs
from telegram_bot import send as tg_send

log = logging.getLogger(__name__)

TIMEZONE = os.environ.get("TIMEZONE", "Europe/Istanbul")
BURC_TIME = os.environ.get("BURC_BATCH_TIME", "06:00")


def _daily_batch_job():
    """Her sabah 12 burç için otomatik üretim ve yükleme."""
    log.info("=" * 50)
    log.info("🔮 Günlük batch başladı")
    tg_send("🌅 <b>Günlük otomatik burç üretimi başladı</b>")

    try:
        results = produce_all_signs(upload=True)
        success_count = len(results["success"])
        fail_count = len(results["failed"])

        msg = (
            f"🏁 <b>Günlük üretim bitti</b>\n"
            f"✅ Başarılı: {success_count}/12\n"
            f"❌ Başarısız: {fail_count}"
        )
        if results["failed"]:
            failed_names = [r["sign_key"] for r in results["failed"]]
            msg += f"\n⚠ {', '.join(failed_names)}"
        tg_send(msg)
    except Exception as e:
        log.exception("Batch genel hatası")
        tg_send(f"❌ Batch hatası: {str(e)[:200]}")


def start_scheduler():
    """APScheduler'ı başlatır. Background modda, Flask ile birlikte çalışır."""
    tz = pytz.timezone(TIMEZONE)
    scheduler = BackgroundScheduler(timezone=tz)

    try:
        hour, minute = map(int, BURC_TIME.split(":"))
    except Exception:
        log.warning(f"Geçersiz BURC_BATCH_TIME '{BURC_TIME}', 06:00 kullanılıyor")
        hour, minute = 6, 0

    scheduler.add_job(
        _daily_batch_job,
        CronTrigger(hour=hour, minute=minute, timezone=tz),
        id="daily_burc_batch",
        name="Günlük 12 Burç Üretimi",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.start()
    log.info(f"📅 Scheduler başladı: her gün {BURC_TIME} ({TIMEZONE})")
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
