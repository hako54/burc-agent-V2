"""
Telegram Bot — Burç Agent
Long polling ile çalışır. Komutlar:
  /burc <burç>   - Tek burç için video üret ve yükle
  /tumburclar    - 12 burç için sırayla üret
  /durum         - Çalışan işlem var mı göster
  /iptal         - Toplu üretimi durdur
  /yardim        - Yardım

Aşama değişimlerini job_tracker üzerinden takip eder ve kullanıcıya
anlamlı ara bildirimler atar.
"""

import os
import time
import logging
import threading
import requests
import urllib3

from zodiac import normalize_sign, all_sign_keys, get_sign
from pipeline import produce_and_upload, produce_all_signs
import job_tracker as jt

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger(__name__)

# Toplu iş bayrağı
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


# ── Aşama Takipçisi ─────────────────────────────────────────────────

def _watch_job_stages(sign_key: str, chat_id: str, info: dict):
    """Bir iş başladıktan sonra arka planda aşama değişimlerini izler
    ve Telegram'a her yeni aşamada mesaj atar. İş bitince kendiliğinden
    durur."""
    last_stage = None
    # Max 20 dakika bekle, sonra bırak (job zaten hata verir)
    for _ in range(240):  # 240 * 5sn = 20 dk
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

    if jt.is_running(sign_key):
        job = jt.get_job(sign_key)
        send(f"⏳ {sign_key.capitalize()} zaten üretiliyor "
             f"({job.get('stage_label', '?')})", chat_id)
        return

    info = get_sign(sign_key)
    send(f"{info['emoji']} <b>{info['name']}</b> burcu üretimi başlıyor...",
         chat_id)

    # İş başlatıldığını tracker'a bildir (telegram'dan geldi bilgisi)
    jt.start_job(sign_key, source="telegram")

    def run():
        try:
            # Aşama bildiricisini paralel başlat
            watcher = threading.Thread(
                target=_watch_job_stages,
                args=(sign_key, chat_id, info),
                daemon=True,
            )
            watcher.start()

            result = produce_and_upload(sign_key, upload=True, source="telegram")
            send(
                f"✅ <b>{info['name']}</b> yayında!\n"
                f"📝 {result.get('title', '')[:80]}\n"
                f"🤖 {result.get('provider', '?')}\n"
                f"🔗 {result.get('youtube_url', '(yok)')}",
                chat_id,
            )
        except Exception as e:
            log.exception(f"cmd_burc({sign_key}) hata")
            send(f"❌ <b>{info['name']}</b> hatası: {str(e)[:200]}", chat_id)

    threading.Thread(target=run, daemon=True).start()


def cmd_tumburclar(chat_id: str):
    global _batch_running
    with _batch_lock:
        if _batch_running:
            send("⏳ Toplu üretim zaten çalışıyor.", chat_id)
            return
        _batch_running = True

    send("🌟 <b>12 burç için üretim başlıyor</b>\n"
         "Yaklaşık 30-60 dakika sürebilir. Her burç için ayrı bildirim alacaksın.",
         chat_id)

    def run():
        global _batch_running
        try:
            success_count = 0
            fail_count = 0
            for i, sign_key in enumerate(all_sign_keys(), 1):
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

                    result = produce_and_upload(sign_key, upload=True,
                                                source="telegram")
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
            title = job.get("title", "")
            source = job.get("source", "?")

            line = f"{info['emoji']} <b>{info['name']}</b> → {stage}"
            if detail:
                line += f"\n   <i>{detail}</i>"
            if title:
                line += f"\n   📝 {title[:60]}"
            if provider:
                line += f" ({provider})"
            line += f"\n   📥 {source}"
            lines.append(line)
            lines.append("")
    else:
        if not _batch_running:
            lines.append("✅ Boşta - çalışan iş yok")

    # Son tamamlananlar
    done = [(k, v) for k, v in jobs.items() if v.get("status") == "done"][-3:]
    if done:
        lines.append("")
        lines.append("📜 <b>Son tamamlananlar:</b>")
        for key, job in done:
            info = get_sign(key)
            url = job.get("youtube_url", "")
            lines.append(f"{info['emoji']} {info['name']} → {url or 'yok'}")

    send("\n".join(lines), chat_id)


def cmd_iptal(chat_id: str):
    global _batch_running
    with _batch_lock:
        if _batch_running:
            _batch_running = False
            send("🛑 Toplu üretim durduruldu (mevcut burç bitince).",
                 chat_id)
        else:
            send("ℹ️ Çalışan toplu üretim yok.", chat_id)


def cmd_yardim(chat_id: str):
    send(
        "🤖 <b>Burç Agent</b>\n\n"
        "🔮 <b>Komutlar:</b>\n"
        "/burc &lt;burç&gt; — Tek burç için video\n"
        "   Örn: /burc koç, /burc aslan\n"
        "/tumburclar — 12 burç için toplu üretim\n"
        "/durum — Canlı durum (hangi aşamada)\n"
        "/iptal — Toplu üretimi durdur\n"
        "/yardim — Bu mesaj\n\n"
        "<i>Aşama değişimlerinde otomatik bildirim alırsın.</i>",
        chat_id,
    )


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
    elif cmd == "/tumburclar":
        cmd_tumburclar(chat_id)
    elif cmd == "/durum":
        cmd_durum(chat_id)
    elif cmd == "/iptal":
        cmd_iptal(chat_id)
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
