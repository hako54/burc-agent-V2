"""
Job Tracker — Tüm kaynaklardan gelen iş durumunu merkezi olarak tutar.
Telegram bot, web panel ve scheduler aynı tracker'ı kullanır.
Bu sayede Telegram'dan başlatılan iş panelde de gözükür ve ters.
"""

import threading
from datetime import datetime
from typing import Optional

# Aşama sabitleri — pipeline boyunca tek tek güncellenir
STAGE_QUEUED = "queued"
STAGE_CONTENT = "content"       # LLM içerik üretiyor
STAGE_IMAGES = "images"         # Pixabay/Pexels görsel indiriliyor
STAGE_TTS = "tts"               # Seslendirme
STAGE_RENDER = "render"         # Video birleştiriliyor
STAGE_UPLOAD = "upload"         # YouTube'a yükleniyor
STAGE_DONE = "done"             # Başarıyla tamamlandı
STAGE_ERROR = "error"           # Hata

STAGE_LABELS = {
    STAGE_QUEUED: "Sıraya alındı",
    STAGE_CONTENT: "Yorum üretiliyor",
    STAGE_IMAGES: "Görseller indiriliyor",
    STAGE_TTS: "Seslendirme yapılıyor",
    STAGE_RENDER: "Video render ediliyor",
    STAGE_UPLOAD: "YouTube'a yükleniyor",
    STAGE_DONE: "Yayında",
    STAGE_ERROR: "Hata",
}

# Basit in-memory store. Süreç restart olursa sıfırlanır, bu kabul edilebilir
# çünkü persistent history zaten data/history.json'a kaydediliyor.
_jobs = {}
_lock = threading.Lock()


def start_job(sign_key: str, source: str = "web") -> dict:
    """Yeni iş başlatır. source: 'web', 'telegram', 'scheduler'."""
    with _lock:
        job = {
            "sign_key": sign_key,
            "status": "running",
            "stage": STAGE_QUEUED,
            "stage_label": STAGE_LABELS[STAGE_QUEUED],
            "source": source,
            "started_at": datetime.now().isoformat(),
            "provider": None,
            "title": None,
            "progress_detail": "",
        }
        _jobs[sign_key] = job
        return dict(job)


def update_stage(sign_key: str, stage: str, detail: str = ""):
    """Aşamayı günceller. detail → alt-metin (örn: 'Seg 3/6 seslendiriliyor')."""
    with _lock:
        if sign_key not in _jobs:
            return
        _jobs[sign_key]["stage"] = stage
        _jobs[sign_key]["stage_label"] = STAGE_LABELS.get(stage, stage)
        _jobs[sign_key]["progress_detail"] = detail
        _jobs[sign_key]["updated_at"] = datetime.now().isoformat()


def set_provider(sign_key: str, provider: str):
    """Hangi LLM'in başarılı olduğunu kaydeder (Claude/Gemini/Groq)."""
    with _lock:
        if sign_key in _jobs:
            _jobs[sign_key]["provider"] = provider


def set_title(sign_key: str, title: str):
    """İçerik üretildikten sonra başlığı kaydeder."""
    with _lock:
        if sign_key in _jobs:
            _jobs[sign_key]["title"] = title


def finish_job(sign_key: str, result: dict = None, error: str = None):
    """İşi tamamlar. result veya error birini ver."""
    with _lock:
        if sign_key not in _jobs:
            return
        if error:
            _jobs[sign_key]["status"] = "error"
            _jobs[sign_key]["stage"] = STAGE_ERROR
            _jobs[sign_key]["stage_label"] = STAGE_LABELS[STAGE_ERROR]
            _jobs[sign_key]["error"] = error
        else:
            _jobs[sign_key]["status"] = "done"
            _jobs[sign_key]["stage"] = STAGE_DONE
            _jobs[sign_key]["stage_label"] = STAGE_LABELS[STAGE_DONE]
            if result:
                _jobs[sign_key]["result"] = result
                _jobs[sign_key]["youtube_url"] = result.get("youtube_url", "")
        _jobs[sign_key]["finished_at"] = datetime.now().isoformat()


def get_job(sign_key: str) -> Optional[dict]:
    with _lock:
        return dict(_jobs[sign_key]) if sign_key in _jobs else None


def all_jobs() -> dict:
    """Tüm işlerin snapshot'ı."""
    with _lock:
        return {k: dict(v) for k, v in _jobs.items()}


def is_running(sign_key: str) -> bool:
    with _lock:
        return (sign_key in _jobs
                and _jobs[sign_key].get("status") == "running")


def clear_old():
    """Tamamlanmış işleri temizler (her 100 işten sonra çağrılabilir).
    Şimdilik manuel — otomatik cleanup eklemiyoruz."""
    with _lock:
        to_remove = [k for k, v in _jobs.items()
                     if v.get("status") in ("done", "error")]
        for k in to_remove:
            del _jobs[k]
