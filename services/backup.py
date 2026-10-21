"""
Günlük şifreli yedek
────────────────────
Volume'deki (DATA_DIR) kalıcı veriler — kanal ayarları, geçmiş, Instagram
token'ı, yorum/isim analizi durumu — her gece tek dosyada toplanır,
şifrelenir ve Telegram'a (bot sohbetine) belge olarak gönderilir. Railway
giderse sistem bu dosyadan başka bir yerde kurulabilir.

Büyük ve yeniden üretilebilir dosyalar (videolar, astrolog klip önbelleği,
Instagram kuyruğundaki videolar) yedeğe girmez.

Şifre: BACKUP_KEY (yoksa PANEL_PASSWORD). Geri yükleme:
    python scripts/restore_backup.py burc_yedek_YYYYMMDD.enc hedef_klasör
"""

import io
import os
import base64
import tarfile
import logging
from pathlib import Path

log = logging.getLogger(__name__)

SKIP_DIRS = {"presenter_cache", "ig_queue", "tmp", "output"}
SKIP_EXT = {".mp4", ".mp3", ".wav", ".mov", ".jpg", ".png", ".tmp"}
MAX_FILE = 5 * 1024 * 1024
MAGIC = b"BURCYEDEK1"


def _password() -> str:
    return os.environ.get("BACKUP_KEY") or os.environ.get("PANEL_PASSWORD", "")


def _fernet(password: str, salt: bytes):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=390000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode())))


def _archive(data_dir: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in sorted(data_dir.rglob("*")):
            rel = p.relative_to(data_dir)
            if (not p.is_file() or rel.parts[0] in SKIP_DIRS
                    or p.suffix.lower() in SKIP_EXT
                    or p.stat().st_size > MAX_FILE):
                continue
            tar.add(p, arcname=str(rel))
    return buf.getvalue()


def make_backup(data_dir: str = None) -> bytes:
    password = _password()
    if not password:
        raise RuntimeError("BACKUP_KEY veya PANEL_PASSWORD tanımlı değil")
    salt = os.urandom(16)
    raw = _archive(Path(data_dir or os.environ.get("DATA_DIR", "data")))
    return MAGIC + salt + _fernet(password, salt).encrypt(raw)


def restore_backup(blob: bytes, dest: str, password: str) -> list:
    """Şifreli yedeği dest klasörüne açar; açılan dosyaları döner."""
    if not blob.startswith(MAGIC):
        raise ValueError("Bu bir burç yedek dosyası değil")
    salt, token = blob[len(MAGIC):len(MAGIC) + 16], blob[len(MAGIC) + 16:]
    raw = _fernet(password, salt).decrypt(token)
    Path(dest).mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")
        return tar.getnames()


def send_backup() -> dict:
    """Yedeği üretip Telegram'a belge olarak gönderir."""
    import requests
    from telegram_bot import _bot_token, _allowed_chat
    from services.tr_locale import now_local
    blob = make_backup()
    name = f"burc_yedek_{now_local().strftime('%Y%m%d')}.enc"
    r = requests.post(
        f"https://api.telegram.org/bot{_bot_token()}/sendDocument",
        data={"chat_id": _allowed_chat(),
              "caption": "🔐 Günlük şifreli yedek (Railway volume)"},
        files={"document": (name, blob, "application/octet-stream")},
        timeout=120)
    r.raise_for_status()
    log.info(f"🔐 Yedek gönderildi: {name} ({len(blob) // 1024} KB)")
    return {"file": name, "size_kb": len(blob) // 1024}


def scheduled_job() -> None:
    if os.environ.get("BACKUP_ENABLED", "1") in ("0", "false"):
        return
    try:
        send_backup()
    except Exception as e:
        log.exception("Günlük yedek alınamadı")
        try:
            from telegram_bot import send as tg_send
            tg_send(f"⚠️ Günlük yedek alınamadı: {str(e)[:200]}")
        except Exception:
            pass
