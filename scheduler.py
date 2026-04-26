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
    """09:00'da çalışır: Her kanal için günün grubundaki 6 burç üretilir,
    YouTube'a 10:00 publishAt ile private yüklenir."""
    log.info("=" * 60)
    today = datetime.now(pytz.timezone(TIMEZONE))
    group = get_todays_group()
    day_type = "ÇİFT" if today.day % 2 == 0 else "TEK"

    log.info(f"🔮 Günlük batch — {today.strftime('%d %B %Y')} ({day_type} gün)")
    log.info(f"   Grup: {', '.join(group)}")

    group_names = ", ".join(get_sign(k)["name"] for k in group)
    publish_at = _calculate_publish_at_iso()
    log.info(f"   YouTube publishAt: {publish_at}")

    # Tüm zodiac tipi kanallar için çalıştır
    import channel_registry as ch_registry
    all_channels = [c for c in ch_registry.list_channels()
                    if c.get("type") == "zodiac"]

    if not all_channels:
        log.warning("Zodiac tipi kanal bulunamadı, batch atlandı")
        return

    tg_send(
        f"🌅 <b>Günlük otomatik üretim</b>\n"
        f"📅 {today.strftime('%d %B %Y')} ({day_type} gün)\n"
        f"🔮 Bugünün burçları: {group_names}\n"
        f"📺 Kanallar: {len(all_channels)}\n"
        f"⏰ Yayın saati: {PUBLISH_TIME}"
    )

    total_success = 0
    total_fail = 0
    failed_details = []

    for ch in all_channels:
        ch_id = ch["id"]
        ch_name = ch["name"]
        log.info(f"  ▶ {ch_name} ({ch_id}) başlıyor...")
        try:
            results = produce_signs(
                group, upload=True, source="scheduler",
                scheduled_publish_at=publish_at,
                channel_id=ch_id,
            )
            s_count = len(results["success"])
            f_count = len(results["failed"])
            total_success += s_count
            total_fail += f_count
            if results["failed"]:
                for r in results["failed"]:
                    failed_details.append(f"{ch_name}/{r['sign_key']}")
            tg_send(
                f"✅ <b>{ch_name}</b>: {s_count}/{len(group)} başarılı"
                + (f" · ❌ {f_count} başarısız" if f_count else "")
            )
        except Exception as e:
            log.exception(f"{ch_name} batch hata")
            total_fail += len(group)
            tg_send(f"❌ <b>{ch_name}</b> batch hatası: {str(e)[:150]}")

    tg_send(
        f"🏁 <b>Günlük batch tamamlandı</b>\n"
        f"✅ Toplam başarılı: {total_success}\n"
        f"❌ Toplam başarısız: {total_fail}\n"
        f"📤 YouTube {PUBLISH_TIME}'da yayınlayacak"
        + (f"\n⚠ Başarısızlar: {', '.join(failed_details[:10])}"
           if failed_details else "")
    )


def _produce_smart_motivation(channel_id: str, time_of_day: str = "sabah",
                              source: str = "scheduler"):
    """Bir motivasyon kanalı için yaratıcı bir konu üret + video yap + yükle."""
    import channel_registry
    from services.topic_suggester import suggest_topic_for_motivation
    from pipeline import produce_content

    channel = channel_registry.get_channel(channel_id)
    if not channel:
        log.warning(f"Kanal bulunamadı: {channel_id}")
        return

    if channel.get("type") != "motivation":
        log.warning(f"Kanal '{channel_id}' motivation tipi değil, atlandı")
        return

    log.info(f"🌱 {channel['name']} ({time_of_day}) smart üretim başlıyor")

    try:
        suggestion = suggest_topic_for_motivation(
            channel_id=channel_id, time_of_day=time_of_day,
        )
        topic = suggestion["topic"]
        slug = suggestion["slug"]

        tg_send(
            f"🌅 <b>{channel['name']} — {time_of_day} üretimi</b>\n"
            f"🤖 Önerilen konu: <i>{topic}</i>\n"
            f"⏳ Üretim başlıyor..."
        )

        result = produce_content(
            channel_id=channel_id,
            topic_key=slug,
            custom_topic=topic,
            upload=True,
            source=source,
            require_approval=False,
        )

        tg_send(
            f"✅ <b>{channel['name']}</b> ({time_of_day}) yayında!\n"
            f"📝 {result.get('title', '')[:80]}\n"
            f"🔗 {result.get('youtube_url', '?')}"
        )
    except Exception as e:
        log.exception(f"Smart üretim {channel_id}/{time_of_day} hata")
        tg_send(
            f"❌ <b>{channel.get('name', channel_id)}</b> "
            f"({time_of_day}) hata: {str(e)[:200]}"
        )


def _morning_motivation_job():
    """10:30'da çalışır: motivasyon tipi auto_schedule'lı kanallar için
    sabah videosu üretir."""
    import channel_registry
    log.info("=" * 60)
    log.info("🌅 Sabah motivasyon üretimi (10:30)")
    motivation_channels = [
        c for c in channel_registry.list_channels()
        if c.get("type") == "motivation" and c.get("auto_schedule", False)
    ]
    if not motivation_channels:
        log.info("Auto-schedule motivasyon kanalı yok, atlandı")
        return
    for ch in motivation_channels:
        _produce_smart_motivation(ch["id"], "sabah", "scheduler")


def _evening_motivation_job():
    """19:00'da çalışır: motivasyon kanalları için akşam videosu."""
    import channel_registry
    log.info("=" * 60)
    log.info("🌆 Akşam motivasyon üretimi (19:00)")
    motivation_channels = [
        c for c in channel_registry.list_channels()
        if c.get("type") == "motivation" and c.get("auto_schedule", False)
    ]
    if not motivation_channels:
        log.info("Auto-schedule motivasyon kanalı yok, atlandı")
        return
    for ch in motivation_channels:
        _produce_smart_motivation(ch["id"], "akşam", "scheduler")


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

    # Motivasyon kanalları için sabah ve akşam yapay zeka destekli üretim
    morning_time = os.environ.get("MOTIVATION_MORNING_TIME", "10:30")
    evening_time = os.environ.get("MOTIVATION_EVENING_TIME", "19:00")
    try:
        mh, mm = map(int, morning_time.split(":"))
        scheduler.add_job(
            _morning_motivation_job,
            CronTrigger(hour=mh, minute=mm, timezone=tz),
            id="morning_motivation",
            name="Sabah Motivasyon (yaratıcı konu)",
            misfire_grace_time=1800,
            replace_existing=True,
        )
        log.info(f"📅 Sabah motivasyon: her gün {morning_time} ({TIMEZONE})")
    except Exception as e:
        log.warning(f"Sabah motivasyon cron eklenemedi: {e}")

    try:
        eh, em = map(int, evening_time.split(":"))
        scheduler.add_job(
            _evening_motivation_job,
            CronTrigger(hour=eh, minute=em, timezone=tz),
            id="evening_motivation",
            name="Akşam Motivasyon (yaratıcı konu)",
            misfire_grace_time=1800,
            replace_existing=True,
        )
        log.info(f"📅 Akşam motivasyon: her gün {evening_time} ({TIMEZONE})")
    except Exception as e:
        log.warning(f"Akşam motivasyon cron eklenemedi: {e}")

    scheduler.start()
    log.info(f"📅 Scheduler başladı: bur\u00e7 {BURC_TIME} "
             f"({TIMEZONE}), bur\u00e7 yay\u0131n {PUBLISH_TIME}")
    log.info(f"   \u00c7ift g\u00fcn: koc, boga, ikizler, yengec, aslan, basak")
    log.info(f"   Tek g\u00fcn:  terazi, akrep, yay, oglak, kova, balik")
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
