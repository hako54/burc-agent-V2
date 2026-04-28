"""
YouTube Upload Servisi (Çoklu Kanal)
Her kanalın kendi OAuth token'ı vardır. Token dosyaları:
  token_<channel_id>.json

Environment variables: TOKEN_<CHANNEL_ID> (base64)
Fallback: credentials_burc.json tüm kanallar için ortak (aynı OAuth Client).

ÖNEMLİ: Sunucuda (Railway) tarayıcı yoktur. Token eksikse lokalde OAuth
yapıp yeni token'i base64 olarak Railway'e taşımak gerekir.
"""

import os
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

CREDS_FILE = "credentials_burc.json"


def _is_server_environment() -> bool:
    """Railway, Heroku vb. sunucu ortamında mıyız?"""
    for marker in ["RAILWAY_ENVIRONMENT", "RENDER", "DYNO", "FLY_APP_NAME",
                   "K_SERVICE"]:
        if os.environ.get(marker):
            return True
    if os.name != "nt" and not os.environ.get("DISPLAY"):
        return True
    return False


def get_youtube_service(channel_id: str = "burc"):
    """Belirli kanal için YouTube API istemcisi oluşturur."""
    token_file = f"token_{channel_id}.json"
    credentials = None

    if os.path.exists(token_file):
        try:
            credentials = Credentials.from_authorized_user_file(token_file, SCOPES)
            log.info(f"{token_file} yüklendi")
        except Exception as e:
            log.warning(f"Token okunamadı ({token_file}): {e}")
    else:
        log.warning(f"{token_file} bulunamadı")

    if credentials and not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            log.info(f"Token yenileniyor ({channel_id})...")
            try:
                credentials.refresh(Request())
                with open(token_file, "w", encoding="utf-8") as f:
                    f.write(credentials.to_json())
                log.info(f"✅ Token yenilendi: {token_file}")
            except Exception as e:
                log.error(f"Token yenilenemedi ({channel_id}): {e}")
                credentials = None
        else:
            log.warning(f"Token geçersiz ({channel_id})")
            credentials = None

    if not credentials:
        if _is_server_environment():
            token_env = f"TOKEN_{channel_id.upper().replace('-', '_')}"
            raise RuntimeError(
                f"❌ '{channel_id}' için YouTube token eksik/geçersiz. "
                f"Sunucuda OAuth başlatılamaz. "
                f"Lokal makinende: "
                f"`python -c \"from services.youtube import get_youtube_service; "
                f"get_youtube_service('{channel_id}')\"` "
                f"Sonra token_{channel_id}.json'u base64'e çevir ve Railway'de "
                f"{token_env} variable'ını güncelle."
            )

        if not os.path.exists(CREDS_FILE):
            raise RuntimeError(
                f"{CREDS_FILE} bulunamadı. OAuth credentials'i "
                f"proje kök klasörüne koy."
            )
        log.info(f"Yeni OAuth akışı ({channel_id}) — tarayıcı açılacak...")
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
        credentials = flow.run_local_server(port=0)

        with open(token_file, "w", encoding="utf-8") as f:
            f.write(credentials.to_json())
        log.info(f"✅ Token kaydedildi: {token_file}")

    return build("youtube", "v3", credentials=credentials,
                 cache_discovery=False)


def upload_video(video_path: str, title: str, description: str,
                 tags: list = None, category_id: str = "22",
                 privacy: str = "public",
                 scheduled_time: str = None,
                 channel_id: str = "burc",
                 thumbnail_path: str = None) -> dict:
    """Video'yu belirli bir kanala yükler. Opsiyonel thumbnail."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video bulunamadı: {video_path}")

    youtube = get_youtube_service(channel_id=channel_id)

    title = (title or "Günlük Yorum")[:100]

    snippet = {
        "title": title,
        "description": description or "",
        "tags": (tags or [])[:15],
        "categoryId": category_id,
    }

    status = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
    }
    if scheduled_time:
        status["privacyStatus"] = "private"
        status["publishAt"] = scheduled_time

    body = {"snippet": snippet, "status": status}

    media = MediaFileUpload(video_path, mimetype="video/mp4",
                            resumable=True, chunksize=1024 * 1024 * 8)

    log.info(f"📤 YouTube'a yükleniyor ({channel_id}): {title}")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    last_progress = 0
    while response is None:
        status_resp, response = request.next_chunk()
        if status_resp:
            progress = int(status_resp.progress() * 100)
            if progress >= last_progress + 10:
                log.info(f"  ... %{progress}")
                last_progress = progress

    video_id = response["id"]
    url = f"https://youtube.com/shorts/{video_id}"
    log.info(f"✅ Yüklendi: {url}")

    # Thumbnail yükle (opsiyonel — başarısız olsa bile video yüklendiği için
    # exception fırlatmıyoruz, sadece log)
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            log.info(f"🎨 Thumbnail yükleniyor: {os.path.basename(thumbnail_path)}")
            thumb_media = MediaFileUpload(thumbnail_path,
                                          mimetype="image/jpeg")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=thumb_media,
            ).execute()
            log.info(f"✅ Thumbnail set: {video_id}")
        except Exception as e:
            log.warning(f"⚠ Thumbnail yüklenemedi (video yüklendi): {e}")

    return {"id": video_id, "url": url, "title": title}
