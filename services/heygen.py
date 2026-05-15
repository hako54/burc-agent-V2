"""
HeyGen API Servisi
─────────────────
Lina (Photo Avatar) ve Charming Ceyda sesiyle video üretimi.

Akış:
1. generate_video() → video_id döner (üretim arka planda başlar)
2. wait_for_video() → video tamamlanana kadar bekler, URL döner
3. download_video() → URL'den dosyaya indir
"""

import os
import time
import logging
import requests

log = logging.getLogger(__name__)

API_BASE = "https://api.heygen.com"


def _api_key() -> str:
    key = os.environ.get("HEYGEN_API_KEY")
    if not key:
        raise RuntimeError("HEYGEN_API_KEY env değişkeni tanımlı değil")
    return key


def _headers(json_content: bool = True) -> dict:
    h = {"X-Api-Key": _api_key()}
    if json_content:
        h["Content-Type"] = "application/json"
    return h


def generate_video(
    avatar_id: str,
    voice_id: str,
    text: str,
    title: str = "soz",
    talking_photo_style: str = None,
    speed: float = 1.0,
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Video üretimini başlatır. video_id döner.

    avatar_id: Lina'nın bir look_id'si (talking_photo)
    voice_id: HeyGen voice_id (Charming Ceyda vs.)
    text: Sözün metni (Türkçe)
    talking_photo_style: None ise HeyGen default kullanılır.
        ('stable' artık desteklenmiyor; gerekirse 'expressive' denenir)
    """
    character = {
        "type": "talking_photo",
        "talking_photo_id": avatar_id,
        "scale": 1.0,
    }
    # talking_photo_style sadece geçerli değerse ekle.
    # HeyGen API "stable" değerini artık desteklemiyor (Nov 2025+).
    if talking_photo_style and talking_photo_style.lower() != "stable":
        character["talking_photo_style"] = talking_photo_style

    payload = {
        "video_inputs": [
            {
                "character": character,
                "voice": {
                    "type": "text",
                    "input_text": text,
                    "voice_id": voice_id,
                    "speed": speed,
                },
            }
        ],
        "dimension": {"width": width, "height": height},
        "title": title[:100],
    }

    log.info(f"HeyGen video başlatılıyor (avatar={avatar_id[:8]}..., "
             f"voice={voice_id[:8]}..., text_len={len(text)})")

    r = requests.post(
        f"{API_BASE}/v2/video/generate",
        headers=_headers(),
        json=payload,
        timeout=60,
        verify=False,
    )

    if r.status_code != 200:
        raise RuntimeError(
            f"HeyGen video/generate HTTP {r.status_code}: {r.text[:400]}"
        )

    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"HeyGen API hatası: {data['error']}")

    video_id = data.get("data", {}).get("video_id")
    if not video_id:
        raise RuntimeError(f"HeyGen video_id dönmedi: {data}")

    log.info(f"✅ HeyGen video başlatıldı: {video_id}")
    return video_id


def get_video_status(video_id: str) -> dict:
    """Video durumunu çeker. Dönüş: {status, video_url, error, ...}

    status değerleri: 'pending', 'processing', 'completed', 'failed'
    """
    r = requests.get(
        f"{API_BASE}/v1/video_status.get",
        headers=_headers(json_content=False),
        params={"video_id": video_id},
        timeout=30,
        verify=False,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"HeyGen video_status HTTP {r.status_code}: {r.text[:200]}"
        )
    return r.json().get("data", {})


def wait_for_video(
    video_id: str,
    max_wait_sec: int = 600,
    poll_interval_sec: int = 10,
) -> str:
    """Video tamamlanana kadar bekler, video_url döner.

    max_wait_sec aşılırsa TimeoutError.
    """
    start = time.time()
    last_status = None
    while time.time() - start < max_wait_sec:
        info = get_video_status(video_id)
        status = info.get("status")

        if status != last_status:
            log.info(f"  ⏳ HeyGen {video_id[:8]}... durum: {status}")
            last_status = status

        if status == "completed":
            url = info.get("video_url")
            if not url:
                raise RuntimeError(
                    f"HeyGen video tamamlandı ama URL boş: {info}"
                )
            elapsed = int(time.time() - start)
            log.info(f"✅ HeyGen video hazır ({elapsed}sn): {video_id}")
            return url

        if status == "failed":
            err = info.get("error") or {}
            msg = err.get("message") or err.get("detail") or str(err)
            raise RuntimeError(f"HeyGen video başarısız: {msg}")

        time.sleep(poll_interval_sec)

    raise TimeoutError(
        f"HeyGen video {video_id} {max_wait_sec}sn içinde tamamlanmadı"
    )


def download_video(url: str, output_path: str, timeout: int = 180) -> str:
    """Video URL'inden dosyaya indir."""
    log.info(f"📥 İndiriliyor: {os.path.basename(output_path)}")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    r = requests.get(url, stream=True, timeout=timeout, verify=False)
    r.raise_for_status()

    total = 0
    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total += len(chunk)

    log.info(f"✅ İndirildi: {output_path} ({total / 1024 / 1024:.1f} MB)")
    return output_path


def list_voices_turkish_female() -> list:
    """Türkçe kadın sesleri listele (debugging için)."""
    r = requests.get(
        f"{API_BASE}/v2/voices",
        headers=_headers(json_content=False),
        timeout=30,
        verify=False,
    )
    r.raise_for_status()
    voices = r.json().get("data", {}).get("voices", [])
    return [
        {"id": v.get("voice_id"), "name": v.get("name")}
        for v in voices
        if (v.get("language", "") or "").lower() == "turkish"
        and (v.get("gender", "") or "").lower() == "female"
    ]


def list_avatar_group_looks(avatar_group_id: str) -> list:
    """Bir avatar grubundaki tüm look'ları listele (debugging için)."""
    r = requests.get(
        f"{API_BASE}/v2/avatar_group/{avatar_group_id}/avatars",
        headers=_headers(json_content=False),
        timeout=30,
        verify=False,
    )
    r.raise_for_status()
    looks = r.json().get("data", {}).get("avatar_list", [])
    return [
        {
            "id": l.get("avatar_id") or l.get("id"),
            "name": l.get("name"),
        }
        for l in looks
    ]
