"""
Onay Kuyruğu
Üretilen ama YouTube'a yüklenmemiş videoları takip eder.
Manuel üretimlerde (Telegram /burc, web panel) bu kuyruğa girer,
kullanıcı onay verene kadar bekler.

Scheduler (09:00 batch) bu kuyruğu atlar, direkt yükler.
"""

import json
import logging
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

PENDING_FILE = Path("data/pending.json")
_lock = threading.Lock()


def _load_pending() -> dict:
    if not PENDING_FILE.exists():
        return {}
    try:
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_pending(data: dict):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_pending(sign_key: str, video_path: str, content: dict,
                source: str = "web"):
    """Üretilmiş videoyu onay kuyruğuna ekler."""
    with _lock:
        pending = _load_pending()
        pending[sign_key] = {
            "sign_key": sign_key,
            "sign_name": content.get("sign_name", ""),
            "title": content.get("title", ""),
            "description": content.get("description", ""),
            "tags": content.get("tags", []),
            "hashtags": content.get("hashtags", []),
            "video_path": video_path,
            "provider": content.get("provider", "?"),
            "created_at": datetime.now().isoformat(),
            "source": source,
        }
        _save_pending(pending)
    log.info(f"Onay kuyruğuna eklendi: {sign_key}")


def get_pending(sign_key: str) -> Optional[dict]:
    """Belirli bir burç için bekleyen onay kaydı."""
    with _lock:
        return _load_pending().get(sign_key)


def list_pending() -> dict:
    """Tüm onay bekleyen kayıtları."""
    with _lock:
        return _load_pending()


def remove_pending(sign_key: str, delete_file: bool = False) -> Optional[dict]:
    """Kaydı kuyruğundan çıkarır. delete_file=True ise video dosyasını da siler."""
    with _lock:
        pending = _load_pending()
        item = pending.pop(sign_key, None)
        if item:
            _save_pending(pending)
            if delete_file and item.get("video_path"):
                try:
                    os.remove(item["video_path"])
                    log.info(f"Video silindi: {item['video_path']}")
                    # JSON metadata dosyasını da sil
                    meta_path = item["video_path"].replace(".mp4", ".json")
                    if os.path.exists(meta_path):
                        os.remove(meta_path)
                except Exception as e:
                    log.warning(f"Video silinemedi: {e}")
        return item


def count_pending() -> int:
    with _lock:
        return len(_load_pending())
