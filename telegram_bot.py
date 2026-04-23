"""
Telegram Bot — Burç Agent (Onay Akışlı)

Komutlar:
  /burc <burç>        - Video üret, ONAY BEKLE
  /yayinla <burç>     - Onaylı videoyu YouTube'a yükle
  /iptal <burç>       - Onay bekleyen videoyu sil
  /bekleyenler        - Onay bekleyen tüm videoları listele
  /tumburclar         - 12 burç batch üretim (onaysız, direkt yükler)
  /durum              - Canlı durum
  /yardim             - Yardım
"""

import os
import time
import logging
import threading
import requests
import urllib3

from zodiac import normalize_sign, all_sign_keys, get_sign
from pipeline import (
    produce_and_upload, produce_all_signs,
    approve_and_upload, reject_pending,
)
import job_tracker as jt
import approval

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger(__name__)

_batch_running = False
_batch_lock = threading.Lock()


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _allowed_chat() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "")


def send(text: str, chat_id: str = None):
    token = _bot_token()
    if not token:
        return
    cid = chat_id or _allowed_chat()
    if not cid:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
            verify=False,
        )
    except Exception as e:
        log.warning(f"Telegram send hata: {e}")


def send_video(video_path: str, caption: str, chat_id: str = None):
    """Video dosyasını Telegram'a gönderir. 50 MB limit."""
    token = _bot_token()
    if not token:
        return False
    cid = chat_id or _allowed_chat()
    if not cid or not os.path.exists(video_path):
        return False

    try:
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if size_mb > 49:
            log.warning(f"Video {size_mb:.1f}MB, Telegram 50MB limitini aşıyor")
            send(
                f"⚠ Video çok büyük ({size_mb:.1f}MB), Telegram'a "
                f"gönderilemedi.\nRailway URL'den izleyebilirsin.",
                cid,
            )
            return False

        log.info(f"Video Telegram'a yükleniyor ({size_mb:.1f}MB)...")
        with open(video_path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={
                    "chat_id": cid,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "supports_streaming": "true",
                },
                files={"video": f},
                timeout=300,
                verify=False,
            )
        if r.status_code == 200:
            return True
        log.warning(f"sendVideo HTTP {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        log.warning(f"Video gönderilemedi: {e}")
        return False


# ── Aşama takipçisi ─────────────────────────────────────────────────

def _watch_job_stages(sign_key: str, chat_id: str, info: dict):
    """İş başladıktan sonra aşama değişimlerini Telegram'a bildirir."""
    last_stage = None
    for _ in range(240):
        job = jt.get_job(sign_key)
        if not job:
            return
        stage = job.get("stage")
        if stage != last_stage and stage not in (jt.STAGE_DONE, jt.STAGE_ERROR):
            label = job.get("stage_label", stage)
            detail = job.get("progress_detail", "")
            emoji = {
                jt.STAGE_CONTENT: "🤖",
                jt.STAGE_IMAGES: "🖼️",
                jt.STAGE_TTS: "🎙",
                jt.STAGE_RENDER: "🎬",
                jt.STAGE_UPLOAD: "📤",
            }.get(stage, "⚙️")
            msg = f"{emoji} {info['emoji']} <b>{info['name']}</b> → {label}"
            if detail:
                msg += f"\n<i>{detail}</i>"
            send(msg, chat_id)
            last_stage = stage
        if job.get("status") in ("done", "error"):
            return
        time.sleep(5)


# ── Komut Handler'lar ───────────────────────────────────────────────

def cmd_burc(chat_id: str, sign_input: str):
    if not sign_input:
        lines = ["🔮 <b>Hangi burcu istersin?</b>", ""]
        for key in all_sign_keys():
            info = get_sign(key)
            lines.append(f"{info['emoji']} /burc {info['name'].lower()}")
        lines.append("")
        lines.append("🌟 Hepsi: /tumburclar")
        send("\n".join(lines), chat_id)
        return

    sign_key = normalize_sign(sign_input)
    if not sign_key:
        send(f"❌ Geçersiz burç: <code>{sign_input}</code>", chat_id)
        return

    # Zaten çalışıyor mu?
    if jt.is_running(sign_key):
        job = jt.get_job(sign_key)
        send(f"⏳ {sign_key.capitalize()} zaten üretiliyor "
             f"({job.get('stage_label', '?')})", chat_id)
        return

    # Daha önce onay bekleyen var mı?
    pending = approval.get_pending(sign_key)
    if pending:
        info = get_sign(sign_key)
        send(
            f"⚠ <b>{info['name']}</b> için zaten onay bekleyen video var:\n"
            f"📝 {pending.get('title', '')[:80]}\n\n"
            f"Önce karar ver:\n"
            f"✅ /yayinla {sign_key}\n"
            f"❌ /iptal {sign_key}",
            chat_id,
        )
        return

    info = get_sign(sign_key)
    send(f"{info['emoji']} <b>{info['name']}</b> burcu üretimi başlıyor...\n"
         f"<i>Üretim sonrası onay isteyeceğim.</i>", chat_id)

    jt.start_job(sign_key, source="telegram")

    def run():
        try:
            watcher = threading.Thread(
                target=_watch_job_stages,
                args=(sign_key, chat_id, info),
                daemon=True,
            )
            watcher.start()

            # require_approval=True → YouTube'a yüklemez, kuyruğa alır
            result = produce_and_upload(
                sign_key, upload=True, source="telegram",
                require_approval=True,
            )

            # Video bilgilerini gönder
            video_path = result.get("video_path", "")
            public_url = _public_video_url(video_path)

            caption = (
                f"✋ <b>{info['name']} onay bekliyor</b>\n\n"
                f"📝 {result.get('title', '')[:90]}\n"
                f"🤖 {result.get('provider', '?')}\n"
            )
            if public_url:
                caption += f"🔗 <a href=\"{public_url}\">Web'de izle</a>\n"
            caption += (
                f"\n<b>Kararını bekliyorum:</b>\n"
                f"✅ /yayinla {sign_key} — YouTube'a yükle\n"
                f"❌ /iptal {sign_key} — Sil"
            )
            send(caption, chat_id)

            # Videoyu da Telegram'a gönder (50MB altındaysa)
            send_video(video_path, f"{info['emoji']} {info['name']} — önizleme",
                       chat_id)

        except Exception as e:
            log.exception(f"cmd_burc({sign_key}) hata")
            send(f"❌ <b>{info['name']}</b> hatası: {str(e)[:200]}", chat_id)

    threading.Thread(target=run, daemon=True).start()


def cmd_yayinla(chat_id: str, sign_input: str):
    """Onaylı videoyu YouTube'a yükler."""
    if not sign_input:
        send("📋 Kullanım: /yayinla &lt;burç&gt;\nÖrn: /yayinla koç", chat_id)
        return

    sign_key = normalize_sign(sign_input)
    if not sign_key:
        send(f"❌ Geçersiz burç: <code>{sign_input}</code>", chat_id)
        return

    pending = approval.get_pending(sign_key)
    if not pending:
        send(f"ℹ️ {sign_key.capitalize()} için onay bekleyen video yok.\n"
             f"Önce /burc {sign_key} ile üret.", chat_id)
        return

    info = get_sign(sign_key)
    send(f"📤 <b>{info['name']}</b> YouTube'a yükleniyor...", chat_id)

    def run():
        try:
            result = approve_and_upload(sign_key, source="telegram")
            send(
                f"✅ <b>{info['name']}</b> yayında!\n"
                f"📝 {result.get('title', '')[:80]}\n"
                f"🔗 {result.get('youtube_url', '?')}",
                chat_id,
            )
        except Exception as e:
            log.exception(f"cmd_yayinla {sign_key} hata")
            send(f"❌ <b>{info['name']}</b> yükleme hatası: "
                 f"{str(e)[:200]}", chat_id)

    threading.Thread(target=run, daemon=True).start()


def cmd_iptal(chat_id: str, sign_input: str):
    """Onay bekleyen videoyu iptal eder (siler)."""
    if not sign_input:
        # Argüman yoksa, batch iptal komutu gibi çalışsın
        global _batch_running
        with _batch_lock:
            if _batch_running:
                _batch_running = False
                send("🛑 Toplu üretim durduruldu.", chat_id)
                return
        send("📋 Kullanım: /iptal &lt;burç&gt;\nÖrn: /iptal koç", chat_id)
        return

    sign_key = normalize_sign(sign_input)
    if not sign_key:
        send(f"❌ Geçersiz burç: <code>{sign_input}</code>", chat_id)
        return

    try:
        item = reject_pending(sign_key)
        info = get_sign(sign_key)
        send(f"🗑 <b>{info['name']}</b> iptal edildi ve silindi.", chat_id)
    except Exception as e:
        send(f"ℹ️ {str(e)[:200]}", chat_id)


def cmd_bekleyenler(chat_id: str):
    """Onay bekleyen tüm videoları listeler."""
    pending = approval.list_pending()
    if not pending:
        send("📭 Onay bekleyen video yok.", chat_id)
        return

    lines = ["📋 <b>Onay Bekleyenler</b>", ""]
    for sign_key, item in pending.items():
        info = get_sign(sign_key)
        lines.append(
            f"{info['emoji']} <b>{info['name']}</b>\n"
            f"   📝 {item.get('title', '')[:60]}\n"
            f"   ✅ /yayinla {sign_key}\n"
            f"   ❌ /iptal {sign_key}"
        )
        lines.append("")
    send("\n".join(lines), chat_id)


def cmd_tumburclar(chat_id: str):
    """12 burç için batch üretim. Onaysız, direkt yükler."""
    global _batch_running
    with _batch_lock:
        if _batch_running:
            send("⏳ Toplu üretim zaten çalışıyor.", chat_id)
            return
        _batch_running = True

    send("🌟 <b>12 burç için üretim başlıyor (onaysız)</b>\n"
         "Yaklaşık 30-60 dakika sürebilir.", chat_id)

    def run():
        global _batch_running
        try:
            success_count = 0
            fail_count = 0
            for i, sign_key in enumerate(all_sign_keys(), 1):
                with _batch_lock:
                    if not _batch_running:
                        send("🛑 İptal edildi.", chat_id)
                        break
                info = get_sign(sign_key)
                try:
                    send(f"[{i}/12] {info['emoji']} <b>{info['name']}</b> "
                         f"başlıyor...", chat_id)

                    jt.start_job(sign_key, source="telegram")
                    watcher = threading.Thread(
                        target=_watch_job_stages,
                        args=(sign_key, chat_id, info),
                        daemon=True,
                    )
                    watcher.start()

                    result = produce_and_upload(
                        sign_key, upload=True, source="telegram",
                        require_approval=False,  # Batch'te onay yok
                    )
                    send(f"✅ [{i}/12] {info['name']} → "
                         f"{result.get('youtube_url', '?')}", chat_id)
                    success_count += 1
                except Exception as e:
                    log.exception(f"{sign_key} batch hata")
                    send(f"❌ [{i}/12] {info['name']}: {str(e)[:150]}",
                         chat_id)
                    fail_count += 1
            send(
                f"🏁 <b>Toplu üretim bitti</b>\n"
                f"✅ Başarılı: {success_count}/12\n"
                f"❌ Başarısız: {fail_count}",
                chat_id,
            )
        finally:
            with _batch_lock:
                _batch_running = False

    threading.Thread(target=run, daemon=True).start()


def cmd_durum(chat_id: str):
    jobs = jt.all_jobs()
    active = [k for k, v in jobs.items() if v.get("status") == "running"]
    pending = approval.list_pending()

    lines = ["📊 <b>Canlı Durum</b>", ""]

    if _batch_running:
        lines.append("🔄 Toplu üretim çalışıyor")
        lines.append("")

    if active:
        for key in active:
            job = jobs[key]
            info = get_sign(key)
            stage = job.get("stage_label", "?")
            detail = job.get("progress_detail", "")
            provider = job.get("provider", "")
            source = job.get("source", "?")

            line = f"{info['emoji']} <b>{info['name']}</b> → {stage}"
            if detail:
                line += f"\n   <i>{detail}</i>"
            if provider:
                line += f" ({provider})"
            lines.append(line)
            lines.append("")
    else:
        if not _batch_running:
            lines.append("✅ Üretim boşta")

    if pending:
        lines.append(f"")
        lines.append(f"✋ <b>Onay bekleyen:</b> {len(pending)}")
        for sign_key in pending:
            info = get_sign(sign_key)
            lines.append(f"   {info['emoji']} {info['name']}")
        lines.append("📋 /bekleyenler yazarak detayı gör")

    send("\n".join(lines), chat_id)


def cmd_yardim(chat_id: str):
    send(
        "🤖 <b>Burç Agent</b>\n\n"
        "🔮 <b>Üretim (onaylı):</b>\n"
        "/burc &lt;burç&gt; — Video üret, onay iste\n"
        "   Örn: /burc koç, /burc aslan\n"
        "/yayinla &lt;burç&gt; — Onaylıyı YouTube'a yükle\n"
        "/iptal &lt;burç&gt; — Onay bekleyeni sil\n"
        "/bekleyenler — Onay bekleyenleri listele\n\n"
        "🌟 <b>Batch (onaysız):</b>\n"
        "/tumburclar — 12 burç direkt yükle\n\n"
        "📊 <b>Diğer:</b>\n"
        "/durum — Canlı durum\n"
        "/iptal — Batch üretimi durdur\n"
        "/yardim — Bu mesaj",
        chat_id,
    )


# ── Yardımcılar ─────────────────────────────────────────────────────

def _public_video_url(video_path: str) -> str:
    """Railway'in public URL'i + output path'i."""
    if not video_path:
        return ""
    filename = os.path.basename(video_path)
    # Railway generates bir domain — RAILWAY_PUBLIC_DOMAIN env var'da
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if domain:
        return f"https://{domain}/output/{filename}"
    return ""


# ── Polling ─────────────────────────────────────────────────────────

def _handle_update(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()

    allowed = _allowed_chat()
    if allowed and chat_id != allowed:
        send("⛔ Yetkisiz.", chat_id)
        return

    if not text.startswith("/"):
        return

    parts = text.split(None, 1)
    cmd = parts[0].lower().split("@")[0]
    args = parts[1].strip() if len(parts) > 1 else ""

    log.info(f"📨 {cmd} {args}")

    if cmd == "/burc":
        cmd_burc(chat_id, args)
    elif cmd == "/yayinla":
        cmd_yayinla(chat_id, args)
    elif cmd == "/iptal":
        cmd_iptal(chat_id, args)
    elif cmd == "/bekleyenler":
        cmd_bekleyenler(chat_id)
    elif cmd == "/tumburclar":
        cmd_tumburclar(chat_id)
    elif cmd == "/durum":
        cmd_durum(chat_id)
    elif cmd in ("/yardim", "/help", "/start"):
        cmd_yardim(chat_id)
    else:
        send(f"❓ Bilinmeyen komut: {cmd}\n/yardim yazarak listeyi gör.",
             chat_id)


def start_polling():
    token = _bot_token()
    if not token:
        log.warning("TELEGRAM_BOT_TOKEN yok, bot başlatılmadı")
        return

    log.info("🤖 Telegram bot başlatıldı")
    send("🤖 Burç Agent aktif!\n/yardim yazarak başla.")

    offset = 0
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                },
                timeout=35,
                verify=False,
            )
            if r.status_code == 200:
                for update in r.json().get("result", []):
                    offset = update["update_id"] + 1
                    try:
                        _handle_update(update)
                    except Exception:
                        log.exception("Update handler hatası")
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            log.warning(f"Polling hatası: {e}")
            time.sleep(5)


def start_background():
    t = threading.Thread(target=start_polling, daemon=True,
                         name="TelegramBot")
    t.start()
    return t


if __name__ == "__main__":
    import bootstrap
    bootstrap.setup_all()
    start_polling()
