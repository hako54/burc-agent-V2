"""
Scheduler — Günlük Otomatik Üretim

Strateji: Gün aşırı 6 burç rotasyonu (YouTube günlük quota sınırı nedeniyle)
- Gruplar her gün sırayla değişir (zodiac.group_for_date):
  Koç, Boğa, İkizler, Yengeç, Aslan, Başak ↔ Terazi, Akrep, Yay, Oğlak,
  Kova, Balık. Ay sonu geçişlerinde de sıra bozulmaz.

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
from services.tr_locale import tr_date
from zodiac import get_todays_group, get_sign, group_label
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
    day_type = group_label(today)

    log.info(f"🔮 Günlük batch — {tr_date(today)} ({day_type})")
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
        f"📅 {tr_date(today)} ({day_type})\n"
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
    """APScheduler'ı başlatır.
    Her kanal için kendi schedule_times'ına göre dinamik cron job
    register eder. auto_schedule=False olan kanallar atlanır."""
    import channel_registry

    tz = pytz.timezone(TIMEZONE)
    scheduler = BackgroundScheduler(timezone=tz)

    job_count = 0
    for ch in channel_registry.list_channels():
        if not ch.get("auto_schedule"):
            continue
        ch_id = ch["id"]
        ch_type = ch.get("type", "zodiac")
        times = ch.get("schedule_times") or []

        for idx, time_str in enumerate(times):
            try:
                h, m = map(int, time_str.split(":"))
            except Exception:
                log.warning(f"Geçersiz saat {ch_id}/{time_str}")
                continue

            job_id = f"auto_{ch_id}_{idx}"

            if ch_type == "zodiac":
                # Burç tipi: günün grubunu üret
                scheduler.add_job(
                    _channel_zodiac_job,
                    CronTrigger(hour=h, minute=m, timezone=tz),
                    args=[ch_id],
                    id=job_id,
                    name=f"Bur\u00e7 {ch_id} {time_str}",
                    misfire_grace_time=3600,
                    replace_existing=True,
                )
            elif ch_type == "motivation":
                # Motivasyon: yaratıcı konu öner üret
                # Saat 06:00-12:00 arası "sabah", sonra "akşam"
                tod = "sabah" if h < 13 else "akşam"
                scheduler.add_job(
                    _channel_motivation_job,
                    CronTrigger(hour=h, minute=m, timezone=tz),
                    args=[ch_id, tod],
                    id=job_id,
                    name=f"Motivasyon {ch_id} {time_str} ({tod})",
                    misfire_grace_time=1800,
                    replace_existing=True,
                )
            elif ch_type == "soz":
                # Söz: HeyGen avatarlı söz videosu
                scheduler.add_job(
                    _channel_soz_job,
                    CronTrigger(hour=h, minute=m, timezone=tz),
                    args=[ch_id],
                    id=job_id,
                    name=f"Söz {ch_id} {time_str}",
                    misfire_grace_time=1800,
                    replace_existing=True,
                )
            else:
                log.info(f"Bilinmeyen tip atlandı: {ch_id} ({ch_type})")
                continue

            job_count += 1
            log.info(f"📅 Cron registered: {ch_id} @ {time_str} "
                     f"({ch_type})")

    scheduler.start()
    log.info(f"📅 Scheduler başladı: {job_count} cron job aktif "
             f"({TIMEZONE})")
    log.info(f"   Bur\u00e7 yay\u0131n saati: {PUBLISH_TIME}")
    return scheduler


def _channel_zodiac_job(channel_id: str):
    """Belirli bir burç kanalı için günün grubunu üretir."""
    import channel_registry
    log.info("=" * 60)
    today = datetime.now(pytz.timezone(TIMEZONE))
    group = get_todays_group()
    day_type = group_label(today)

    log.info(f"🔮 Bur\u00e7 batch: {channel_id} — "
             f"{tr_date(today)} ({day_type})")

    channel = channel_registry.get_channel(channel_id)
    if not channel:
        log.warning(f"Kanal yok: {channel_id}")
        return

    publish_at = _calculate_publish_at_iso()
    group_names = ", ".join(get_sign(k)["name"] for k in group)
    tg_send(
        f"🌅 <b>{channel['name']}</b> otomatik üretim\n"
        f"📅 {tr_date(today)} ({day_type})\n"
        f"🔮 {group_names}\n"
        f"⏰ Yay\u0131n: {PUBLISH_TIME}"
    )

    try:
        results = produce_signs(
            group, upload=True, source="scheduler",
            scheduled_publish_at=publish_at,
            channel_id=channel_id,
        )
        s = len(results["success"])
        f = len(results["failed"])
        msg = f"✅ <b>{channel['name']}</b>: {s}/{len(group)} ba\u015far\u0131l\u0131"
        if f:
            msg += f"\n❌ {f} ba\u015far\u0131s\u0131z"
        tg_send(msg)
    except Exception as e:
        log.exception(f"Burç batch {channel_id} hata")
        tg_send(f"❌ <b>{channel['name']}</b> hata: {str(e)[:200]}")


def _channel_motivation_job(channel_id: str, time_of_day: str):
    """Motivasyon kanalı için yaratıcı konu önerip üretir."""
    _produce_smart_motivation(channel_id, time_of_day, "scheduler")


def _produce_soz(channel_id: str, source: str = "scheduler"):
    """Söz kanalı için HeyGen tabanlı söz üretir.

    LLM söz + mood etiketleri üretir, modül en uygun temayı eşleştirir,
    HeyGen avatar video çeker. Pipeline'a 'auto' topic ile gider.
    """
    import channel_registry
    from pipeline import produce_content

    channel = channel_registry.get_channel(channel_id)
    if not channel:
        log.warning(f"Kanal bulunamadı: {channel_id}")
        return

    if channel.get("type") != "soz":
        log.warning(f"Kanal '{channel_id}' soz tipi değil, atlandı")
        return

    log.info(f"💭 {channel['name']} söz üretimi başlıyor")

    try:
        tg_send(
            f"💭 <b>{channel['name']} — söz üretimi</b>\n"
            f"⏳ HeyGen ile video çekiliyor (~1-3 dk)..."
        )

        result = produce_content(
            channel_id=channel_id,
            topic_key="auto",
            upload=True,
            source=source,
            require_approval=False,
        )

        theme_name = (result.get("theme_name") or
                      result.get("heygen_theme_name") or "?")
        tg_send(
            f"✅ <b>{channel['name']}</b> yayında!\n"
            f"📝 {result.get('title', '')[:80]}\n"
            f"🎭 Tema: {theme_name}\n"
            f"🔗 {result.get('youtube_url', '?')}"
        )
    except Exception as e:
        log.exception(f"Söz üretim {channel_id} hata")
        tg_send(
            f"❌ <b>{channel.get('name', channel_id)}</b> "
            f"söz hatası: {str(e)[:200]}"
        )


def _channel_soz_job(channel_id: str):
    """Söz kanalı için cron job."""
    _produce_soz(channel_id, "scheduler")


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
