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

ÖNEMLİ: Sunucuda (Railway) tarayıcı yoktur. OAuth akışı yalnızca LOKAL
makinede başlatılabilir. Token eksikse açık ve anlaşılır hata fırlatırız.
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


def _is_server_environment() -> bool:
    """Railway, Heroku veya başka bir sunucu ortamında mıyız tespit eder.
    Bu ortamlarda tarayıcı açılamaz, OAuth başlatılamaz."""
    # Railway, Render, Fly vs otomatik env var'lar
    server_markers = [
        "RAILWAY_ENVIRONMENT",
        "RENDER",
        "DYNO",          # Heroku
        "FLY_APP_NAME",
        "K_SERVICE",     # Google Cloud Run
    ]
    for marker in server_markers:
        if os.environ.get(marker):
            return True
    # DISPLAY yoksa X olmayan sistem
    if os.name != "nt" and not os.environ.get("DISPLAY"):
        return True
    return False


def get_youtube_service():
    """YouTube API istemcisi oluşturur. Token yoksa veya süresi dolduysa yeniler.
    Sunucuda tarayıcı açılamaz, net hata fırlatır."""
    credentials = None

    if os.path.exists(TOKEN_FILE):
        try:
            credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            log.info("token_burc.json yüklendi")
        except Exception as e:
            log.warning(f"Token okunamadı: {e}")
            credentials = None
    else:
        log.warning(f"{TOKEN_FILE} bulunamadı")

    # Token var ama geçersizse, refresh dene
    if credentials and not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            log.info("Token süresi dolmuş, yenileniyor...")
            try:
                credentials.refresh(Request())
                # Yenilenmiş token'i geri kaydet
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(credentials.to_json())
                log.info("✅ Token yenilendi")
            except Exception as e:
                log.error(f"Token yenilenemedi: {e}")
                credentials = None
        else:
            log.warning("Token geçersiz ve refresh_token yok")
            credentials = None

    # Hala credentials yoksa — OAuth başlatmak gerekir
    if not credentials:
        if _is_server_environment():
            # Bulutta tarayıcı açamayız. Net hata.
            raise RuntimeError(
                "❌ YouTube token eksik veya geçersiz. "
                "Sunucuda OAuth akışı başlatılamaz (tarayıcı yok). "
                "ÇÖZÜM: Lokal makinende `python -c \"from services.youtube "
                "import get_youtube_service; get_youtube_service()\"` "
                "çalıştır, yeni token_burc.json oluştur, onu base64'e çevir "
                "ve Railway'de TOKEN_BURC variable'ını güncelle."
            )

        # Lokalde — tarayıcıyı açıp OAuth akışı başlat
        if not os.path.exists(CREDS_FILE):
            raise RuntimeError(
                f"{CREDS_FILE} bulunamadı. Google Cloud Console'dan "
                "OAuth Desktop Client credentials indir ve proje kök "
                "klasörüne koy."
            )
        log.info("Yeni OAuth akışı başlatılıyor (yerel tarayıcı açılacak)...")
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
        credentials = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(credentials.to_json())
        log.info(f"✅ Token kaydedildi: {TOKEN_FILE}")

    return build("youtube", "v3", credentials=credentials,
                 cache_discovery=False)


def upload_video(video_path: str, title: str, description: str,
                 tags: list = None, category_id: str = "22",
                 privacy: str = "public",
                 scheduled_time: str = None) -> dict:
    """Video'yu YouTube'a yükler. Dönüş: {'id': video_id, 'url': youtube_url}."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video bulunamadı: {video_path}")

    youtube = get_youtube_service()

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
