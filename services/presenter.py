"""
AI astrolog sunucu (HeyGen)
───────────────────────────
Burç videolarının açılışında ve kapanışında kadın astrolog sunucu konuşur;
ortadaki yorum eskisi gibi görseller + seslendirme ile devam eder.

Ses bütünlüğü için sunucu kendi HeyGen sesini kullanmaz: açılış/kapanış
metni önce bizim TTS'imizle (ElevenLabs → Edge → gTTS) seslendirilir,
HeyGen bu ses dosyasına dudak senkronu yapar. Böylece videonun tamamında
aynı ses duyulur.

Ayarlar (Railway değişkenleri):
  HEYGEN_API_KEY             — zorunlu
  HEYGEN_PRESENTER_AVATAR_ID — zorunlu; sunucunun talking_photo / look id'si
  ZODIAC_PRESENTER           — "0" ise sunucu kapalı (varsayılan açık)
  HEYGEN_PRESENTER_AVATAR_IV — "0" ise ucuz motor (varsayılan Avatar IV)
  PRESENTER_NAME             — opsiyonel; "Ben astrolog <ad>" der
  PRESENTER_TIMEOUT          — HeyGen bekleme süresi, sn (varsayılan 900)
  PRESENTER_OUTRO            — "0" ise sunucu sadece açılışta konuşur
                               (kredi tasarrufu; varsayılan açık)
  PRESENTER_CACHE            — "0" ise klipler saklanmaz (varsayılan açık)

Klip önbelleği: açılış/kapanış cümlelerinde tarih ya da yorum yok
(açılış sadece burç adına göre değişir). Bu yüzden HeyGen'in ürettiği her
klip DATA_DIR/presenter_cache altına (Railway volume) kaydedilir ve aynı
cümle tekrar gerektiğinde HeyGen'e gidilmez. Cümleler tarihe göre sırayla
seçildiği için birkaç günde tüm çeşitler birikir; sonrasında günlük HeyGen
harcaması sıfıra iner. Anahtar metin + avatar + motor + ses ayarından
türetilir; bunlardan biri değişirse yeni klip üretilir.

Herhangi bir adım başarısız olursa video eski açılış/kapanışla üretilir.
"""

import os
import json
import time
import shutil
import hashlib
import logging
import threading
from datetime import date
from pathlib import Path

import requests

from services import heygen

log = logging.getLogger(__name__)

UPLOAD_URL = "https://upload.heygen.com/v1/asset"

MOTION_PROMPT = (
    "A warm, charismatic female astrologer speaks directly to the camera "
    "with confident, engaging energy. She uses graceful hand gestures, "
    "gentle head tilts and expressive eyes, as if sharing a secret about "
    "the stars. Small natural body movements and breathing."
)

_INTROS = [
    "Merhaba sevgili {sign} burçları! {me}Bugün yıldızlar sizin için "
    "neler söylüyor, hemen bakalım.",
    "Sevgili {sign} burçları, hoş geldiniz! {me}Bugün gökyüzünde size "
    "özel mesajlar var, kaçırmayın.",
    "{sign} burçları, bugün sizin gününüz olabilir! {me}Yıldızların "
    "fısıldadıklarına birlikte bakalım.",
]

_OUTROS = [
    "Yorumu beğendiyseniz abone olmayı unutmayın. Yarın yıldızlarla "
    "yeniden buluşalım!",
    "Yarın yeni yorumlarla buradayım. Abone olun, yıldızlar sizinle olsun!",
    "Bu enerjiyi bir arkadaşınızla paylaşın. Yarın görüşmek üzere, "
    "yıldızlar sizinle olsun!",
]


def _flag(name: str, default: bool = True) -> bool:
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val not in ("0", "false", "off", "no", "hayir", "hayır")


def avatar_id() -> str:
    return os.environ.get("HEYGEN_PRESENTER_AVATAR_ID", "").strip()


def enabled() -> bool:
    """Sunucu kullanılabilir mi? (anahtar + avatar + açık)"""
    return (_flag("ZODIAC_PRESENTER")
            and bool(os.environ.get("HEYGEN_API_KEY"))
            and bool(avatar_id()))


def outro_enabled() -> bool:
    """Kapanışta da sunucu konuşsun mu? (PRESENTER_OUTRO=0 → sadece açılış)"""
    return _flag("PRESENTER_OUTRO")


# ── Hata bildirimi ───────────────────────────────────────────────────
# Kredi bittiğinde 6 burç × 2 klip = 12 aynı hata olur; Telegram'a tek
# mesaj gitsin ve o turdaki diğer burçlar HeyGen'i boşuna denemesin.
_ALERT_WINDOW = 6 * 3600
_CREDIT_BLOCK = 2 * 3600
_lock = threading.Lock()
_last_alert = {}
_blocked_until = 0.0


def _is_credit_error(err) -> bool:
    msg = str(err).lower()
    return "insufficient credit" in msg or "quota" in msg


def blocked() -> bool:
    """Kredi bittiği yakın zamanda görüldüyse True (HeyGen'i deneme)."""
    return time.time() < _blocked_until


def report_failure(part: str, sign: str, err) -> None:
    """Sunucu üretilemediğinde Telegram'a (kısıtlı sıklıkta) haber verir."""
    global _blocked_until
    credit = _is_credit_error(err)
    kind = "credit" if credit else "other"
    now = time.time()
    with _lock:
        if credit:
            _blocked_until = now + _CREDIT_BLOCK
        if now - _last_alert.get(kind, 0) < _ALERT_WINDOW:
            return
        _last_alert[kind] = now
    if credit:
        text = ("⚠️ <b>HeyGen API kredisi bitti</b>\n"
                "Burç videoları astrolog sunucu olmadan (klasik açılışla) "
                "üretiliyor. HeyGen hesabına <b>API kredisi</b> yükleyince "
                "sunucu bir sonraki üretimde kendiliğinden geri gelir.")
    else:
        text = (f"⚠️ <b>Astrolog sunucu üretilemedi</b> ({sign}, {part})\n"
                f"Video klasik sürümle üretildi.\nHata: "
                f"{str(err)[:300]}")
    try:
        from telegram_bot import send as tg_send
        tg_send(text)
    except Exception as e:
        log.warning(f"Sunucu hata bildirimi gönderilemedi: {e}")


def _variant(n: int, day: date = None, every: int = 1) -> int:
    """Tarihe göre sıradaki çeşit (rastgele değil: önbellek tekrar
    kullanılabilsin ve aynı cümle arka arkaya gelmesin)."""
    return ((day or date.today()).toordinal() // every) % n


def intro_line(sign_name: str, day: date = None) -> str:
    name = os.environ.get("PRESENTER_NAME", "").strip()
    me = f"Ben astrolog {name}. " if name else ""
    # Her burç 2 günde bir çıkar → her çıkışında bir sonraki çeşit
    tpl = _INTROS[_variant(len(_INTROS), day, every=2)]
    return tpl.format(sign=sign_name, me=me)


def outro_line(day: date = None) -> str:
    return _OUTROS[_variant(len(_OUTROS), day)]


# ── Klip önbelleği ──────────────────────────────────────────────────

def _cache_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "presenter_cache"


def cache_key(part: str, text: str, voice_config: dict = None) -> str:
    raw = json.dumps([avatar_id(), _flag("HEYGEN_PRESENTER_AVATAR_IV"),
                      text, voice_config or {}],
                     sort_keys=True, ensure_ascii=False, default=str)
    return f"{part}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def cached_clip(key: str):
    """Önbellekte geçerli bir klip varsa yolunu döner."""
    if not _flag("PRESENTER_CACHE"):
        return None
    path = _cache_dir() / f"{key}.mp4"
    try:
        if path.stat().st_size > 10_000:
            return str(path)
    except OSError:
        pass
    return None


def save_clip(key: str, src_path: str) -> None:
    if not _flag("PRESENTER_CACHE"):
        return
    try:
        d = _cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{key}.tmp"
        shutil.copyfile(src_path, tmp)
        os.replace(tmp, d / f"{key}.mp4")
        log.info(f"🎭 Sunucu klibi önbelleğe alındı: {key}")
    except Exception as e:
        log.warning(f"Sunucu klibi önbelleğe alınamadı: {e}")


def _upload_audio(audio_path: str) -> str:
    with open(audio_path, "rb") as f:
        data = f.read()
    r = requests.post(
        UPLOAD_URL,
        headers={"X-Api-Key": heygen._api_key(),
                 "Content-Type": "audio/mpeg"},
        data=data,
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"HeyGen ses yükleme HTTP {r.status_code}: {r.text[:300]}")
    asset_id = (r.json().get("data") or {}).get("id")
    if not asset_id:
        raise RuntimeError(f"HeyGen ses yükleme id dönmedi: {r.text[:300]}")
    return asset_id


def start_clip(audio_path: str, title: str) -> str:
    """Ses dosyasını yükler ve sunucu videosunu başlatır; video_id döner."""
    asset_id = _upload_audio(audio_path)
    use_iv = _flag("HEYGEN_PRESENTER_AVATAR_IV")
    payload = {
        "video_inputs": [{
            "character": {
                "type": "talking_photo",
                "talking_photo_id": avatar_id(),
                "scale": 1.0,
            },
            "voice": {"type": "audio", "audio_asset_id": asset_id},
        }],
        "dimension": {"width": 1080, "height": 1920},
        "title": title[:100],
    }
    if use_iv:
        payload["use_avatar_iv_model"] = True
        payload["custom_motion_prompt"] = MOTION_PROMPT
    r = requests.post(f"{heygen.API_BASE}/v2/video/generate",
                      headers=heygen._headers(), json=payload, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(
            f"HeyGen video/generate HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"HeyGen API hatası: {data['error']}")
    video_id = (data.get("data") or {}).get("video_id")
    if not video_id:
        raise RuntimeError(f"HeyGen video_id dönmedi: {data}")
    log.info(f"🎭 Sunucu klibi başlatıldı ({title}, IV={use_iv}): {video_id}")
    return video_id


def fetch_clip(video_id: str, output_path: str) -> str:
    """Sunucu videosu bitene kadar bekler ve indirir."""
    timeout = int(os.environ.get("PRESENTER_TIMEOUT", "900") or 900)
    url = heygen.wait_for_video(video_id, max_wait_sec=timeout,
                                poll_interval_sec=10)
    return heygen.download_video(url, output_path)


def list_talking_photos() -> list:
    """Hesaptaki fotoğraf avatarları (sunucu seçmek için)."""
    r = requests.get(f"{heygen.API_BASE}/v2/avatars",
                     headers=heygen._headers(json_content=False), timeout=30)
    r.raise_for_status()
    data = r.json().get("data") or {}
    return [
        {"id": p.get("talking_photo_id"), "name": p.get("talking_photo_name"),
         "preview": p.get("preview_image_url")}
        for p in data.get("talking_photos") or []
    ]


def list_avatar_groups() -> list:
    """Fotoğraf avatar grupları ve look'ları (AI ile üretilen avatarlar
    look olarak burada görünür)."""
    r = requests.get(f"{heygen.API_BASE}/v2/avatar_group.list",
                     headers=heygen._headers(json_content=False), timeout=30)
    r.raise_for_status()
    groups = (r.json().get("data") or {}).get("avatar_group_list") or []
    out = []
    for g in groups[:20]:
        gid = g.get("id") or g.get("group_id")
        item = {"group_id": gid, "name": g.get("name")}
        try:
            item["looks"] = heygen.list_avatar_group_looks(gid)
        except Exception as e:
            item["looks_error"] = str(e)[:200]
        out.append(item)
    return out
