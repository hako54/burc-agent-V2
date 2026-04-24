"""
Onay Kuyruğu (Çoklu Kanal)
Her kanal için ayrı pending dosyası:
  data/<channel_id>/pending.json
"""

import json
import logging
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
_lock = threading.Lock()


def _pending_file(channel_id: str = "burc") -> Path:
    return DATA_DIR / channel_id / "pending.json"


def _load_pending(channel_id: str = "burc") -> dict:
    path = _pending_file(channel_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_pending(data: dict, channel_id: str = "burc"):
    path = _pending_file(channel_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_pending(sign_key: str, video_path: str, content: dict,
                source: str = "web", channel_id: str = "burc"):
    """Üretilmiş videoyu onay kuyruğuna ekler."""
    with _lock:
        pending = _load_pending(channel_id)
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
            "channel_id": channel_id,
        }
        _save_pending(pending, channel_id)
    log.info(f"Onay kuyruğuna eklendi: {channel_id}/{sign_key}")


def get_pending(sign_key: str, channel_id: str = "burc") -> Optional[dict]:
    with _lock:
        return _load_pending(channel_id).get(sign_key)


def list_pending(channel_id: str = "burc") -> dict:
    """Bir kanalın onay bekleyen kayıtları."""
    with _lock:
        return _load_pending(channel_id)


def list_all_pending() -> dict:
    """Tüm kanalların onay bekleyenlerini birleştirir.
    Dönüş: {channel_id: {sign_key: item}}"""
    with _lock:
        all_pending = {}
        if not DATA_DIR.exists():
            return all_pending
        for subdir in DATA_DIR.iterdir():
            if subdir.is_dir() and (subdir / "pending.json").exists():
                ch_id = subdir.name
                all_pending[ch_id] = _load_pending(ch_id)
        return all_pending


def remove_pending(sign_key: str, delete_file: bool = False,
                   channel_id: str = "burc") -> Optional[dict]:
    """Kaydı çıkarır. delete_file=True ise video dosyasını da siler."""
    with _lock:
        pending = _load_pending(channel_id)
        item = pending.pop(sign_key, None)
        if item:
            _save_pending(pending, channel_id)
            if delete_file and item.get("video_path"):
                try:
                    os.remove(item["video_path"])
                    log.info(f"Video silindi: {item['video_path']}")
                    meta_path = item["video_path"].replace(".mp4", ".json")
                    if os.path.exists(meta_path):
                        os.remove(meta_path)
                except Exception as e:
                    log.warning(f"Video silinemedi: {e}")
        return item


def count_pending(channel_id: str = "burc") -> int:
    with _lock:
        return len(_load_pending(channel_id))
