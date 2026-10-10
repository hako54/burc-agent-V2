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

Herhangi bir adım başarısız olursa video eski açılış/kapanışla üretilir.
"""

import os
import random
import logging

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


def intro_line(sign_name: str) -> str:
    name = os.environ.get("PRESENTER_NAME", "").strip()
    me = f"Ben astrolog {name}. " if name else ""
    return random.choice(_INTROS).format(sign=sign_name, me=me)


def outro_line() -> str:
    return random.choice(_OUTROS)


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
