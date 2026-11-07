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


def _jpeg(raw: bytes) -> bytes:
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def upload_to_heygen(name: str, group_id: str = "") -> dict:
    """Onaylanan adayı HeyGen'e yükler. group_id verilirse (varsayılan:
    asıl Astrolog avatarının grubu) ayrı avatar yerine o gruba "look"
    olarak eklenir — HeyGen'in fotoğraf avatarı sınırına takılmaz."""
    from services import heygen, presenter
    name = _safe(name)
    data = _load()
    look = data["looks"].get(name)
    if not look:
        raise ValueError(f"Aday yok: {name}")
    raw = _jpeg((_dir() / look["file"]).read_bytes())
    group_id = group_id or os.environ.get(
        "HEYGEN_LOOK_GROUP_ID", "") or presenter.avatar_id()
    # 1) Görseli asset olarak yükle → image_key
    r = requests.post("https://upload.heygen.com/v1/asset",
                      headers={"X-Api-Key": heygen._api_key(),
                               "Content-Type": "image/jpeg"},
                      data=raw, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"HeyGen görsel yükleme HTTP {r.status_code}: "
                           f"{r.text[:300]}")
    d = r.json().get("data") or {}
    key = d.get("image_key")
    if not key:
        raise RuntimeError(f"image_key dönmedi: {r.text[:300]}")
    before = {l["id"] for l in heygen.list_avatar_group_looks(group_id)}
    # 2) Gruba look olarak ekle
    r = requests.post(f"{heygen.API_BASE}/v2/photo_avatar/avatar_group/add",
                      headers=heygen._headers(),
                      json={"group_id": group_id, "image_keys": [key],
                            "name": f"Astrolog {name}"}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HeyGen look ekleme HTTP {r.status_code}: "
                           f"{r.text[:300]}")
    # 3) Yeni look'un id'sini bul (işlenmesi birkaç saniye sürebilir)
    import time
    tid = None
    for _ in range(12):
        new = [l["id"] for l in heygen.list_avatar_group_looks(group_id)
               if l["id"] not in before]
        if new:
            tid = new[0]
            break
        time.sleep(5)
    if not tid:
        raise RuntimeError(f"Look eklendi ama id bulunamadı: {r.text[:300]}")
    look["heygen_id"] = tid
    look["group_id"] = group_id
    _save(data)
    log.info(f"🎭 Ortam HeyGen'e look olarak eklendi: {name} → {tid}")
    return {"name": name, "heygen_id": tid, "group_id": group_id}


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


_gen_status = {}


def generate_with_heygen(name: str, prompt: str, pose: str = "half_body",
                         group_id: str = "") -> dict:
    """HeyGen'in kendi görünüm üreticisiyle (Astrolog grubundan) yeni bir
    görsel üretir; bitince aday olarak kaydedip Telegram'a gönderir.
    Arka planda çalışır; durum: generation_status(name)."""
    import threading
    from services import heygen, presenter
    name = _safe(name)
    group_id = group_id or os.environ.get(
        "HEYGEN_LOOK_GROUP_ID", "") or presenter.avatar_id()
    body = {"group_id": group_id, "prompt": prompt[:1000],
            "orientation": "vertical", "pose": pose, "style": "Realistic"}
    r = requests.post(f"{heygen.API_BASE}/v2/photo_avatar/look/generate",
                      headers=heygen._headers(), json=body, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HeyGen look üretimi HTTP {r.status_code}: "
                           f"{r.text[:400]}")
    gid = (r.json().get("data") or {}).get("generation_id")
    if not gid:
        raise RuntimeError(f"generation_id dönmedi: {r.text[:300]}")
    _gen_status[name] = {"status": "running", "generation_id": gid}

    def poll():
        import time
        try:
            for _ in range(90):
                time.sleep(10)
                g = requests.get(
                    f"{heygen.API_BASE}/v2/photo_avatar/generation/{gid}",
                    headers=heygen._headers(json_content=False), timeout=30)
                d = (g.json() or {}).get("data") or {}
                st = (d.get("status") or "").lower()
                if st in ("success", "completed"):
                    urls = d.get("image_url_list") or []
                    keys = d.get("image_key_list") or []
                    _gen_status[name].update(status="done", urls=urls,
                                             keys=keys)
                    for i, u in enumerate(urls[:4]):
                        nm = f"{name}{chr(97 + i)}" if len(urls) > 1 else name
                        add_candidate(u, nm, f"🎭 HeyGen görünüm adayı: {nm}")
                        if i < len(keys):
                            data = _load()
                            data["looks"][nm]["image_key"] = keys[i]
                            _save(data)
                    return
                if st in ("failed", "error"):
                    _gen_status[name].update(status="error",
                                             error=str(d)[:300])
                    return
            _gen_status[name].update(status="timeout")
        except Exception as e:
            log.exception("HeyGen görünüm üretimi")
            _gen_status[name].update(status="error", error=str(e)[:300])

    threading.Thread(target=poll, daemon=True).start()
    return {"name": name, "generation_id": gid}


def generation_status(name: str) -> dict:
    return _gen_status.get(_safe(name), {"status": "unknown"})
