"""
YouTube Upload Servisi
OAuth 2.0 ile kimlik doğrulama + video yükleme.

Kimlik bilgileri:
- credentials_burc.json (OAuth client bilgileri)
- token_burc.json (ilk yetkilendirme sonrası otomatik oluşur)

Bu dosyalar Railway'de environment variable olarak saklanır:
- CREDENTIALS_BURC (base64)
- TOKEN_BURC (base64)
Uygulama başlarken bootstrap.py bunları dosyaya dönüştürür.
"""

import os
import logging
import httplib2
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

TOKEN_FILE = "token_burc.json"
CREDS_FILE = "credentials_burc.json"


def get_youtube_service():
    """YouTube API istemcisi oluşturur. Token yoksa veya süresi dolduysa yeniler."""
    credentials = None

    if os.path.exists(TOKEN_FILE):
        try:
            credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            log.warning(f"Token okunamadı: {e}")
            credentials = None

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            log.info("Token süresi dolmuş, yenileniyor...")
            try:
                credentials.refresh(Request())
            except Exception as e:
                log.error(f"Token yenilenemedi: {e}")
                credentials = None

        if not credentials:
            if not os.path.exists(CREDS_FILE):
                raise RuntimeError(
                    f"{CREDS_FILE} bulunamadı. Google Cloud Console'dan "
                    "OAuth Desktop Client credentials indir ve proje kök "
                    "klasörüne koy."
                )
            log.info("Yeni OAuth akışı başlatılıyor...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            credentials = flow.run_local_server(port=0)

        # Yeni/yenilenmiş token'i kaydet
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(credentials.to_json())
        log.info(f"✅ Token kaydedildi: {TOKEN_FILE}")

    return build("youtube", "v3", credentials=credentials,
                 cache_discovery=False)


def upload_video(video_path: str, title: str, description: str,
                 tags: list = None, category_id: str = "22",
                 privacy: str = "public",
                 scheduled_time: str = None) -> dict:
    """Video'yu YouTube'a yükler. Dönüş: {'id': video_id, 'url': youtube_url}.

    Args:
        video_path: Yerel video dosya yolu
        title: Video başlığı (max 100 karakter, YouTube limit)
        description: Açıklama metni
        tags: Tag listesi (max 15 önerilen)
        category_id: YouTube kategori ID'si. 22=People&Blogs, 24=Entertainment,
                     28=Science&Tech. Astroloji için 22 veya 24.
        privacy: 'public', 'unlisted', veya 'private'
        scheduled_time: ISO 8601 tarih (gelecek). Verilirse privacy 'private' olur.

    Returns:
        {'id': str, 'url': str, 'title': str}
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video bulunamadı: {video_path}")

    youtube = get_youtube_service()

    # Title YouTube'da max 100 karakter
    title = (title or "Günlük Burç Yorumu")[:100]

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
    # Scheduled upload: privacy zorunlu olarak 'private'
    if scheduled_time:
        status["privacyStatus"] = "private"
        status["publishAt"] = scheduled_time

    body = {"snippet": snippet, "status": status}

    media = MediaFileUpload(video_path, mimetype="video/mp4",
                            resumable=True, chunksize=1024 * 1024 * 8)

    log.info(f"📤 YouTube'a yükleniyor: {title}")
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
            # %10'luk dilimlerle log
            if progress >= last_progress + 10:
                log.info(f"  ... %{progress}")
                last_progress = progress

    video_id = response["id"]
    url = f"https://youtube.com/shorts/{video_id}"
    log.info(f"✅ Yüklendi: {url}")

    return {
        "id": video_id,
        "url": url,
        "title": title,
    }
