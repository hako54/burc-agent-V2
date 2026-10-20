"""
Instagram (Reels) yayını
────────────────────────
Burç videoları YouTube'a yüklendikten sonra Instagram'a Reels olarak da
paylaşılır. Resmi Instagram API'si (Instagram Login ile, Professional
hesap) kullanılır.

Akış:
1. enqueue(): video + dikey kapak (videonun ilk karesi) DATA_DIR/ig_queue
   altına (Railway volume) kopyalanır, yayın zamanı ile kuyruğa eklenir.
   Volume'de durduğu için arada yeniden kurulum olsa bile kaybolmaz.
2. process_queue(): scheduler her birkaç dakikada çağırır; zamanı gelen
   kayıtlardan BİRİNİ yayınlar (6 burç ~5 dk arayla düşer).
3. Instagram videoyu bizim sunucudan indirir: /pub/<imza>/<dosya> adresi
   şifresiz ama imzalı (tahmin edilemez) bir bağlantıdır.

Ayarlar (Railway değişkenleri):
  IG_ACCESS_TOKEN   — zorunlu; uzun ömürlü (60 gün) Instagram token'ı.
                      Kod 20 günde bir kendiliğinden yeniler ve yenisini
                      volume'de saklar.
  IG_USER_ID        — opsiyonel; boşsa /me'den alınır
  INSTAGRAM_CHANNELS— Instagram'a gidecek kanallar (varsayılan "burc")
  INSTAGRAM_ENABLED — "0" ise kapalı
  PUBLIC_BASE_URL   — opsiyonel; boşsa RAILWAY_PUBLIC_DOMAIN kullanılır
"""

import os
import json
import time
import hmac
import shutil
import hashlib
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
GRAPH = f"https://graph.instagram.com/{API_VERSION}"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
REFRESH_EVERY = 20 * 86400
MAX_ATTEMPTS = 3

_lock = threading.Lock()


# ── Ayarlar ──────────────────────────────────────────────────────────

def _flag(name: str, default: bool = True) -> bool:
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val not in ("0", "false", "off", "no", "hayir", "hayır")


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data"))


def _queue_dir() -> Path:
    return _data_dir() / "ig_queue"


def _queue_file() -> Path:
    return _data_dir() / "instagram_queue.json"


def _token_file() -> Path:
    return _data_dir() / "instagram_token.json"


def enabled() -> bool:
    return _flag("INSTAGRAM_ENABLED") and bool(_token())


def channel_enabled(channel_id: str) -> bool:
    chans = os.environ.get("INSTAGRAM_CHANNELS", "burc")
    return enabled() and channel_id in [c.strip() for c in chans.split(",")]


# ── Token ────────────────────────────────────────────────────────────

def _load_saved_token() -> dict:
    try:
        return json.loads(_token_file().read_text())
    except Exception:
        return {}


def _token() -> str:
    """Volume'deki yenilenmiş token, yoksa env'deki. Env token'ı
    değiştirilirse (kullanıcı yeni token girdi) env olan kazanır."""
    env_tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    saved = _load_saved_token()
    if saved.get("token") and saved.get("env_hash") == _hash(env_tok):
        return saved["token"]
    return env_tok


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def refresh_token_if_needed(force: bool = False) -> bool:
    """Uzun ömürlü token'ı 20 günde bir yeniler (60 günde biter)."""
    env_tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not env_tok:
        return False
    saved = _load_saved_token()
    same_env = saved.get("env_hash") == _hash(env_tok)
    last = saved.get("refreshed_at", 0) if same_env else 0
    if not force and same_env and time.time() - last < REFRESH_EVERY:
        return False
    try:
        r = requests.get(REFRESH_URL, params={
            "grant_type": "ig_refresh_token",
            "access_token": _token(),
        }, timeout=30)
        data = r.json()
        if r.status_code != 200 or "access_token" not in data:
            log.warning(f"Instagram token yenilenemedi: {str(data)[:200]}")
            return False
        _data_dir().mkdir(parents=True, exist_ok=True)
        _token_file().write_text(json.dumps({
            "token": data["access_token"],
            "env_hash": _hash(env_tok),
            "refreshed_at": time.time(),
            "expires_in": data.get("expires_in"),
        }))
        log.info("🔑 Instagram token yenilendi")
        return True
    except Exception as e:
        log.warning(f"Instagram token yenileme hatası: {e}")
        return False


# ── API ──────────────────────────────────────────────────────────────

def _api(method: str, path: str, **params) -> dict:
    params["access_token"] = _token()
    r = requests.request(method, f"{GRAPH}/{path}",
                         params=params if method == "GET" else None,
                         data=params if method != "GET" else None,
                         timeout=60)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:300]}
    if r.status_code != 200 or "error" in data:
        err = data.get("error", data)
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"Instagram API {r.status_code}: {msg}")
    return data


def send_private_reply(user_id: str, comment_id: str, text: str) -> dict:
    """Yorum yapan kişiye DM (Instagram Private Replies). Yorum başına bir
    kez ve yorumdan sonraki 7 gün içinde gönderilebilir. Takipçilere
    gönderebilmek için uygulamanın Meta onayı (Advanced Access,
    instagram_business_manage_messages) gerekir."""
    r = requests.post(f"{GRAPH}/{user_id}/messages",
                      params={"access_token": _token()},
                      json={"recipient": {"comment_id": comment_id},
                            "message": {"text": text[:1000]}},
                      timeout=60)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:300]}
    if r.status_code != 200 or "error" in data:
        err = data.get("error", data)
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"Instagram DM {r.status_code}: {msg}")
    return data


def account_info() -> dict:
    return _api("GET", "me", fields="user_id,username,account_type,"
                "media_count,followers_count")


def _user_id() -> str:
    uid = os.environ.get("IG_USER_ID", "").strip()
    if uid:
        return uid
    return str(account_info().get("user_id"))


def publish_reel(video_url: str, caption: str, cover_url: str = None,
                 max_wait: int = 600) -> dict:
    """Reels yayınlar; {id, permalink} döner."""
    uid = _user_id()
    params = {"media_type": "REELS", "video_url": video_url,
              "caption": caption[:2200], "share_to_feed": "true"}
    if cover_url:
        params["cover_url"] = cover_url
    container = _api("POST", f"{uid}/media", **params)["id"]
    log.info(f"📸 Instagram konteyner oluşturuldu: {container}")

    start = time.time()
    while True:
        st = _api("GET", container, fields="status_code,status")
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram video işlenemedi: "
                               f"{st.get('status')}")
        if time.time() - start > max_wait:
            raise TimeoutError("Instagram video işleme zaman aşımı")
        time.sleep(10)

    media_id = _api("POST", f"{uid}/media_publish",
                    creation_id=container)["id"]
    try:
        link = _api("GET", media_id, fields="permalink").get("permalink")
    except Exception:
        link = ""
    log.info(f"✅ Instagram'da yayında: {link or media_id}")
    return {"id": media_id, "permalink": link}


# ── İmzalı herkese açık bağlantı ─────────────────────────────────────

def _link_secret() -> str:
    return (os.environ.get("PUBLIC_LINK_SECRET")
            or os.environ.get("ADMIN_KEY")
            or os.environ.get("PANEL_PASSWORD") or "")


def sign(filename: str) -> str:
    secret = _link_secret()
    if not secret:
        return ""
    return hmac.new(secret.encode(), filename.encode(),
                    hashlib.sha256).hexdigest()[:32]


def verify(sig: str, filename: str) -> bool:
    expected = sign(filename)
    return bool(expected) and hmac.compare_digest(sig, expected)


def public_file_path(filename: str):
    path = (_queue_dir() / filename).resolve()
    if path.parent != _queue_dir().resolve() or not path.exists():
        return None
    return path


def _public_url(filename: str) -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
        base = f"https://{domain}" if domain else ""
    sig = sign(filename)
    if not base or not sig:
        raise RuntimeError("Herkese açık bağlantı üretilemedi "
                           "(RAILWAY_PUBLIC_DOMAIN / ADMIN_KEY eksik)")
    return f"{base}/pub/{sig}/{filename}"


# ── Kuyruk ───────────────────────────────────────────────────────────

def _load_queue() -> list:
    try:
        return json.loads(_queue_file().read_text())
    except Exception:
        return []


def _save_queue(items: list) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    tmp = _queue_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    os.replace(tmp, _queue_file())


def queue_status() -> list:
    return _load_queue()


def build_caption(title: str, description: str, hashtags: list,
                  sign_name: str = "") -> str:
    tags = list(dict.fromkeys(
        (hashtags or []) + ["#burç", "#astroloji", "#günlükburç",
                            "#burçyorumu", "#reels", "#keşfet"]))[:25]
    parts = [title.strip()]
    if description:
        parts.append(description.strip())
    parts.append("Burcunu yorumlara yaz, sana özel mesajı kaçırma! 💬✨")
    parts.append(" ".join(t if t.startswith("#") else f"#{t}" for t in tags))
    return "\n\n".join(p for p in parts if p)


def _first_frame(video_path: str, out_path: str) -> bool:
    """Reels kapağı: videonun ilk karesi (sunucu + dev merak cümlesi)."""
    try:
        from moviepy.editor import VideoFileClip
        from PIL import Image
        clip = VideoFileClip(video_path)
        frame = clip.get_frame(min(0.3, max(0.0, clip.duration - 0.1)))
        clip.close()
        Image.fromarray(frame).save(out_path, "JPEG", quality=90)
        return True
    except Exception as e:
        log.warning(f"Instagram kapağı çıkarılamadı: {e}")
        return False


def enqueue(channel_id: str, topic_key: str, video_path: str,
            caption: str, publish_after: str = None,
            cut_at: float = None, cover_path: str = None) -> dict:
    """Videoyu (ve kapağını) volume'e kopyalayıp kuyruğa ekler. cut_at
    verilirse Instagram'a videonun kısa (vurucu) kesiti gider."""
    qd = _queue_dir()
    qd.mkdir(parents=True, exist_ok=True)
    stem = f"{channel_id}_{topic_key}_{int(time.time())}"
    vname = f"{stem}.mp4"
    done = False
    if cut_at:
        try:
            from services.ig_reels import make_short_cut
            make_short_cut(video_path, str(qd / vname), cut_at)
            done = True
        except Exception as e:
            log.warning(f"Kısa kesit üretilemedi, tam video gidecek: {e}")
    if not done:
        shutil.copyfile(video_path, qd / vname)
    cname = f"{stem}_cover.jpg"
    if cover_path and os.path.exists(cover_path):
        shutil.copyfile(cover_path, qd / cname)
    elif not _first_frame(str(qd / vname), str(qd / cname)):
        cname = ""
    item = {
        "id": stem, "channel_id": channel_id, "topic_key": topic_key,
        "video": vname, "cover": cname, "caption": caption,
        "publish_after": publish_after or datetime.now(
            timezone.utc).isoformat(),
        "attempts": 0, "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        items = _load_queue()
        items.append(item)
        _save_queue(items)
    log.info(f"📸 Instagram kuyruğuna eklendi: {stem} "
             f"(yayın: {item['publish_after']})")
    return item


def _due(item: dict) -> bool:
    try:
        t = datetime.fromisoformat(item["publish_after"].replace("Z",
                                                                 "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t <= datetime.now(timezone.utc)
    except Exception:
        return True


def _remove_files(item: dict) -> None:
    for name in (item.get("video"), item.get("cover")):
        if name:
            try:
                (_queue_dir() / name).unlink()
            except OSError:
                pass


def _notify(text: str) -> None:
    try:
        from telegram_bot import send as tg_send
        tg_send(text)
    except Exception:
        pass


def process_queue() -> None:
    """Zamanı gelmiş ilk kaydı yayınlar (her çağrıda en fazla bir tane)."""
    if not enabled():
        return
    refresh_token_if_needed()
    with _lock:
        items = _load_queue()
        item = next((i for i in items if _due(i)), None)
    if not item:
        return
    try:
        cover = _public_url(item["cover"]) if item.get("cover") else None
        res = publish_reel(_public_url(item["video"]), item["caption"],
                           cover_url=cover)
        with _lock:
            _save_queue([i for i in _load_queue() if i["id"] != item["id"]])
        _remove_files(item)
        _notify(f"📸 <b>Instagram'da yayında</b>\n"
                f"{item['caption'].splitlines()[0][:90]}\n"
                f"{res.get('permalink', '')}")
    except Exception as e:
        log.warning(f"Instagram yayını başarısız ({item['id']}): {e}")
        attempts = MAX_ATTEMPTS
        with _lock:
            items = _load_queue()
            for i in items:
                if i["id"] == item["id"]:
                    i["attempts"] = i.get("attempts", 0) + 1
                    i["last_error"] = str(e)[:300]
                    attempts = i["attempts"]
            if attempts >= MAX_ATTEMPTS:
                items = [i for i in items if i["id"] != item["id"]]
            _save_queue(items)
        if attempts >= MAX_ATTEMPTS:
            _remove_files(item)
            _notify(f"⚠️ <b>Instagram yayını yapılamadı</b> "
                    f"({item['topic_key']}, {MAX_ATTEMPTS} deneme)\n"
                    f"Hata: {str(e)[:250]}")
