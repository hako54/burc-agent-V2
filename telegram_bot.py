"""
Telegram Bot — Burç Agent
Long polling ile çalışır. Komutlar:
  /burc <burç>   - Tek burç için video üret ve yükle
  /tumburclar    - 12 burç için sırayla üret
  /durum         - Çalışan işlem var mı göster
  /iptal         - Toplu üretimi durdur
  /yardim        - Yardım

Kurumsal ağlarda SSL proxy'lerini bypass etmek için verify=False kullanır.
"""

import os
import time
import logging
import threading
import requests
import urllib3

from zodiac import normalize_sign, all_sign_keys, get_sign
from pipeline import produce_and_upload, produce_all_signs

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger(__name__)

# Durum bayrakları — thread-safe basit yaklaşım
_running = {}


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _allowed_chat() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "")


def send(text: str, chat_id: str = None):
    """Telegram'a mesaj gönderir. HTML formatlaması destekler."""
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


# ── Komut Handler'lar ───────────────────────────────────────────────

def cmd_burc(chat_id: str, sign_input: str):
    """/burc <burç> komutu — tek burç için akış."""
    if not sign_input:
        # Menü göster
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

    lock = f"burc_{sign_key}"
    if _running.get(lock):
        send(f"⏳ {sign_key.capitalize()} zaten üretiliyor, bekle.", chat_id)
        return
    _running[lock] = True

    info = get_sign(sign_key)
    send(f"{info['emoji']} <b>{info['name']}</b> burcu üretimi başladı...",
         chat_id)

    def run():
        try:
            send("🤖 Yorum üretiliyor...", chat_id)
            result = produce_and_upload(sign_key, upload=True)
            send(
                f"✅ <b>{info['name']}</b> yayında!\n"
                f"📝 {result.get('title', '')[:80]}\n"
                f"🤖 {result.get('provider', '?')} | "
                f"🔗 {result.get('youtube_url', '(yok)')}",
                chat_id,
            )
        except Exception as e:
            log.exception(f"cmd_burc({sign_key}) hata")
            send(f"❌ <b>{info['name']}</b> hatası: {str(e)[:200]}", chat_id)
        finally:
            _running[lock] = False

    threading.Thread(target=run, daemon=True).start()


def cmd_tumburclar(chat_id: str):
    """/tumburclar — 12 burç için sırayla."""
    if _running.get("batch"):
        send("⏳ Toplu üretim zaten çalışıyor.", chat_id)
        return
    _running["batch"] = True
    send("🌟 <b>12 burç için üretim başlıyor</b>\n"
         "Yaklaşık 30-60 dakika sürebilir.", chat_id)

    def run():
        try:
            success_count = 0
            fail_count = 0
            for i, sign_key in enumerate(all_sign_keys(), 1):
                if not _running.get("batch"):
                    send("🛑 İptal edildi.", chat_id)
                    break
                info = get_sign(sign_key)
                try:
                    send(f"[{i}/12] {info['emoji']} <b>{info['name']}</b>...",
                         chat_id)
                    result = produce_and_upload(sign_key, upload=True)
                    send(
                        f"✅ [{i}/12] {info['name']} → "
                        f"{result.get('youtube_url', '?')}",
                        chat_id,
                    )
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
            _running["batch"] = False

    threading.Thread(target=run, daemon=True).start()


def cmd_durum(chat_id: str):
    """/durum — çalışan işlem var mı?"""
    lines = ["📊 <b>Durum</b>", ""]
    batch = _running.get("batch", False)
    active_signs = [
        k.replace("burc_", "") for k in _running
        if k.startswith("burc_") and _running[k]
    ]
    if batch:
        lines.append("🔄 Toplu üretim çalışıyor")
    elif active_signs:
        lines.append(f"🔄 Aktif: {', '.join(active_signs)}")
    else:
        lines.append("✅ Boşta")
    send("\n".join(lines), chat_id)


def cmd_iptal(chat_id: str):
    """/iptal — çalışan toplu üretimi durdur."""
    stopped = []
    for k in list(_running.keys()):
        if _running.get(k):
            _running[k] = False
            stopped.append(k)
    if stopped:
        send(f"🛑 Durduruldu: {', '.join(stopped)}", chat_id)
    else:
        send("ℹ️ Çalışan işlem yok.", chat_id)


def cmd_yardim(chat_id: str):
    send(
        "🤖 <b>Burç Agent</b>\n\n"
        "🔮 <b>Komutlar:</b>\n"
        "/burc &lt;burç&gt; — Tek burç için video\n"
        "   Örn: /burc koç, /burc aslan\n"
        "/tumburclar — 12 burç için toplu üretim\n"
        "/durum — Çalışan işlemi göster\n"
        "/iptal — Toplu üretimi durdur\n"
        "/yardim — Bu mesaj",
        chat_id,
    )


# ── Polling ─────────────────────────────────────────────────────────

def _handle_update(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()

    # Yetkisiz erişim kontrolü
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
    """Long polling ile bot'u çalıştır. Engelleyen çağrı."""
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
    """Bot'u arka plan thread'de başlatır. Flask app içinden çağrılır."""
    t = threading.Thread(target=start_polling, daemon=True,
                         name="TelegramBot")
    t.start()
    return t


if __name__ == "__main__":
    import bootstrap
    bootstrap.setup_all()
    start_polling()
