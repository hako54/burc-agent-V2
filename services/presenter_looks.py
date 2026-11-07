"""
Astroloğun farklı ortamları ("look"lar)
───────────────────────────────────────
Aynı kadının farklı mekânlarda üretilmiş fotoğrafları önce aday olarak
volume'e kaydedilip Telegram'a gönderilir; onaylananlar HeyGen'e
talking photo olarak yüklenir ve özel liste videolarında sırayla kullanılır.

Kayıt: DATA_DIR/presenter_looks/{name}.png ve looks.json
  {"looks": {name: {"file": ..., "heygen_id": ... | null}}}
"""

import os
import re
import json
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

PHOTO_UPLOAD_URL = "https://upload.heygen.com/v1/talking_photo"


def _dir() -> Path:
    d = Path(os.environ.get("DATA_DIR", "data")) / "presenter_looks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load() -> dict:
    try:
        return json.loads((_dir() / "looks.json").read_text(encoding="utf-8"))
    except Exception:
        return {"looks": {}}


def _save(data: dict) -> None:
    (_dir() / "looks.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _safe(name: str) -> str:
    name = re.sub(r"[^a-z0-9_-]", "", (name or "").lower())
    if not name:
        raise ValueError("Geçersiz isim")
    return name


def add_candidate(url: str, name: str, caption: str = "") -> dict:
    """Görseli indirip kaydeder ve Telegram'a (sıkıştırmasız) gönderir."""
    name = _safe(name)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    path = _dir() / f"{name}.png"
    path.write_bytes(r.content)
    data = _load()
    data["looks"].setdefault(name, {})["file"] = path.name
    _save(data)
    from telegram_bot import _bot_token, _allowed_chat
    tr = requests.post(
        f"https://api.telegram.org/bot{_bot_token()}/sendPhoto",
        data={"chat_id": _allowed_chat(),
              "caption": caption or f"🎭 Astrolog ortamı adayı: {name}"},
        files={"photo": (path.name, r.content, "image/png")}, timeout=120)
    tr.raise_for_status()
    log.info(f"🎭 Ortam adayı kaydedildi ve gönderildi: {name}")
    return {"name": name, "size_kb": len(r.content) // 1024}


def upload_to_heygen(name: str) -> dict:
    """Onaylanan adayı HeyGen'e talking photo olarak yükler."""
    from services import heygen
    name = _safe(name)
    data = _load()
    look = data["looks"].get(name)
    if not look:
        raise ValueError(f"Aday yok: {name}")
    raw = (_dir() / look["file"]).read_bytes()
    # HeyGen JPEG/PNG kabul eder; boyutu küçültmek için JPEG'e çevir
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92)
        raw, ctype = buf.getvalue(), "image/jpeg"
    except Exception:
        ctype = "image/png"
    r = requests.post(PHOTO_UPLOAD_URL,
                      headers={"X-Api-Key": heygen._api_key(),
                               "Content-Type": ctype},
                      data=raw, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"HeyGen fotoğraf yükleme HTTP {r.status_code}: "
                           f"{r.text[:300]}")
    tid = (r.json().get("data") or {}).get("talking_photo_id")
    if not tid:
        raise RuntimeError(f"HeyGen yanıtında id yok: {r.text[:300]}")
    look["heygen_id"] = tid
    _save(data)
    log.info(f"🎭 Ortam HeyGen'e yüklendi: {name} → {tid}")
    return {"name": name, "heygen_id": tid}


def remove(name: str) -> None:
    data = _load()
    data["looks"].pop(_safe(name), None)
    _save(data)


def active_ids() -> list:
    """HeyGen'e yüklenmiş ortamların id'leri (isim sırasıyla)."""
    looks = _load()["looks"]
    return [looks[k]["heygen_id"] for k in sorted(looks)
            if looks[k].get("heygen_id")]


def status() -> dict:
    return _load()
