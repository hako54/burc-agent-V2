"""
İş İptali Mekanizması
Her üretim bir Thread'de çalışır. İptal için threading.Event kullanıyoruz.
Render sırasında Event'i kontrol edip "iptal edildi" exception'ı fırlatıyoruz.

Kaynak tahmini (yaklaşık):
- Content üretimi (LLM): ~1 saniye CPU
- Görseller: ~5 sn, 3-6 MB
- TTS (ElevenLabs): 1500 karakter × $0.00003 = ~$0.04
- Video render: ~60-90 sn CPU
- YouTube upload: ~1 dk, 1600 quota
"""

import logging
import threading
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

# İş bazlı iptal event'leri
# key: job_key, value: threading.Event
_cancel_events: dict[str, threading.Event] = {}

# İş bazlı kaynak tüketim istatistikleri
# key: job_key, value: dict
_resources: dict[str, dict] = {}

_lock = threading.Lock()


def register_job(job_key: str) -> threading.Event:
    """Bir iş için iptal event'i oluşturur ve döner.
    İş kendi içinde bu event'i check_is_cancelled() ile kontrol eder."""
    with _lock:
        event = threading.Event()
        _cancel_events[job_key] = event
        _resources[job_key] = {
            "started_at": datetime.now().isoformat(),
            "llm_calls": 0,
            "images_fetched": 0,
            "tts_chars": 0,
            "render_started": False,
            "upload_started": False,
            "cancelled": False,
        }
    return event


def is_cancelled(job_key: str) -> bool:
    with _lock:
        event = _cancel_events.get(job_key)
    return event.is_set() if event else False


def cancel_job(job_key: str) -> bool:
    """Bir işi iptal eder. Başarılı ise True döner."""
    with _lock:
        event = _cancel_events.get(job_key)
        if event:
            event.set()
            if job_key in _resources:
                _resources[job_key]["cancelled"] = True
                _resources[job_key]["cancelled_at"] = datetime.now().isoformat()
            log.info(f"⛔ İş iptal edildi: {job_key}")
            return True
    return False


def cleanup_job(job_key: str):
    """İş bittiğinde event ve kaynak kaydını temizler."""
    with _lock:
        _cancel_events.pop(job_key, None)
        # _resources'ı tutuyoruz ki UI görüntüleyebilsin, ama eskiler temizlensin


def record_llm_call(job_key: str, chars_in: int = 0, chars_out: int = 0):
    with _lock:
        if job_key in _resources:
            _resources[job_key]["llm_calls"] += 1
            _resources[job_key].setdefault("llm_chars_in", 0)
            _resources[job_key].setdefault("llm_chars_out", 0)
            _resources[job_key]["llm_chars_in"] += chars_in
            _resources[job_key]["llm_chars_out"] += chars_out


def record_image(job_key: str):
    with _lock:
        if job_key in _resources:
            _resources[job_key]["images_fetched"] += 1


def record_tts(job_key: str, chars: int):
    with _lock:
        if job_key in _resources:
            _resources[job_key]["tts_chars"] += chars


def mark_render_started(job_key: str):
    with _lock:
        if job_key in _resources:
            _resources[job_key]["render_started"] = True


def mark_upload_started(job_key: str):
    with _lock:
        if job_key in _resources:
            _resources[job_key]["upload_started"] = True


def get_resource_report(job_key: str) -> Optional[dict]:
    """İş sırasında/sonrasında harcanan kaynakların özeti."""
    with _lock:
        r = _resources.get(job_key)
        if not r:
            return None
        r = dict(r)  # kopya

    # Tahmini maliyet hesabı
    tts_cost_usd = r.get("tts_chars", 0) * 0.00003  # $0.03/1k char
    llm_cost_usd = 0.02 if r.get("llm_calls", 0) > 0 else 0  # Haiku ~2 cent
    youtube_quota = 1600 if r.get("upload_started") else 0

    r["estimated_cost_usd"] = round(tts_cost_usd + llm_cost_usd, 4)
    r["youtube_quota_used"] = youtube_quota

    # Human-readable özet
    lines = []
    if r.get("llm_calls"):
        lines.append(f"🤖 LLM: {r['llm_calls']} çağrı")
    if r.get("images_fetched"):
        lines.append(f"🖼 Görsel: {r['images_fetched']} indirildi")
    if r.get("tts_chars"):
        lines.append(f"🎙 TTS: {r['tts_chars']} karakter (~${tts_cost_usd:.3f})")
    if r.get("render_started"):
        lines.append(f"🎬 Render: başladı")
    if r.get("upload_started"):
        lines.append(f"📤 Upload: başladı ({youtube_quota} quota)")

    r["summary_lines"] = lines
    return r


class JobCancelled(Exception):
    """Bir iş iptal edildiğinde fırlatılan exception."""
    pass


def check_is_cancelled(job_key: str):
    """Render/upload adımlarında çağrılır. İş iptal edildiyse
    JobCancelled exception'ı fırlatır."""
    if is_cancelled(job_key):
        raise JobCancelled(f"İş iptal edildi: {job_key}")
