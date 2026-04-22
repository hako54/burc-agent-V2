"""
Flask Web Uygulaması
Railway'de çalışan ana servis. İçeriği:
- Web paneli (templates/dashboard.html)
- REST API endpoints
- Telegram bot (arka plan thread)
- Günlük scheduler (arka plan)
- Sağlık kontrolü (/health)
"""

import os
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from flask import (
    Flask, render_template, jsonify, request,
    send_from_directory, abort
)

import bootstrap
bootstrap.setup_all()  # Ortam hazırlığı burada olmalı (logging, credentials)

from zodiac import ZODIAC_SIGNS, normalize_sign, get_sign, all_sign_keys
from pipeline import produce_and_upload, produce_all_signs
from telegram_bot import start_background as start_telegram_bg
from scheduler import start_scheduler

log = logging.getLogger(__name__)

app = Flask(__name__)

# Üretim durumu (thread-safe basit dict)
_jobs = {}
_jobs_lock = threading.Lock()


# ── Web Paneli ──────────────────────────────────────────────────────

@app.route("/")
def index():
    """Ana dashboard sayfası."""
    return render_template("dashboard.html")


@app.route("/health")
def health():
    """Railway için sağlık kontrolü."""
    return jsonify({
        "status": "ok",
        "time": datetime.now().isoformat(),
    })


# ── REST API ────────────────────────────────────────────────────────

@app.route("/api/signs")
def api_signs():
    """12 burç bilgilerini döner (panel için)."""
    signs = []
    for key in all_sign_keys():
        info = get_sign(key)
        signs.append({
            "key": key,
            "name": info["name"],
            "symbol": info["symbol"],
            "emoji": info["emoji"],
            "element": info["element"],
            "dates": info["dates"],
            "color": info["color"],
        })
    return jsonify({"signs": signs})


@app.route("/api/produce/<sign_key>", methods=["POST"])
def api_produce(sign_key):
    """Bir burç için üretim başlatır (arka planda çalışır).
    Body: {"upload": true|false}   (varsayılan: true)
    """
    key = normalize_sign(sign_key)
    if not key:
        return jsonify({"error": "Geçersiz burç"}), 400

    data = request.get_json(silent=True) or {}
    upload = bool(data.get("upload", True))

    job_id = f"{key}_{datetime.now().strftime('%H%M%S')}"

    with _jobs_lock:
        if _jobs.get(key, {}).get("status") == "running":
            return jsonify({"error": "Bu burç için işlem zaten çalışıyor",
                           "job": _jobs[key]}), 409
        _jobs[key] = {
            "id": job_id,
            "sign_key": key,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "upload": upload,
        }

    def run():
        try:
            result = produce_and_upload(key, upload=upload)
            with _jobs_lock:
                _jobs[key] = {
                    **_jobs[key],
                    "status": "done",
                    "finished_at": datetime.now().isoformat(),
                    "result": result,
                }
        except Exception as e:
            log.exception(f"Job {job_id} hata")
            with _jobs_lock:
                _jobs[key] = {
                    **_jobs[key],
                    "status": "error",
                    "finished_at": datetime.now().isoformat(),
                    "error": str(e),
                }

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id, "sign_key": key, "status": "running"})


@app.route("/api/produce-all", methods=["POST"])
def api_produce_all():
    """12 burç için batch üretim başlatır."""
    data = request.get_json(silent=True) or {}
    upload = bool(data.get("upload", True))

    with _jobs_lock:
        if _jobs.get("__batch__", {}).get("status") == "running":
            return jsonify({"error": "Batch zaten çalışıyor"}), 409
        _jobs["__batch__"] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
        }

    def run():
        try:
            results = produce_all_signs(upload=upload)
            with _jobs_lock:
                _jobs["__batch__"] = {
                    "status": "done",
                    "started_at": _jobs["__batch__"]["started_at"],
                    "finished_at": datetime.now().isoformat(),
                    "success_count": len(results["success"]),
                    "fail_count": len(results["failed"]),
                    "results": results,
                }
        except Exception as e:
            log.exception("Batch hata")
            with _jobs_lock:
                _jobs["__batch__"] = {
                    "status": "error",
                    "finished_at": datetime.now().isoformat(),
                    "error": str(e),
                }

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "running"})


@app.route("/api/jobs")
def api_jobs():
    """Aktif ve tamamlanmış işleri döner."""
    with _jobs_lock:
        return jsonify({"jobs": dict(_jobs)})


@app.route("/api/history")
def api_history():
    """Geçmiş kayıtları döner (son 50)."""
    history_file = Path("data/history.json")
    if not history_file.exists():
        return jsonify({"history": []})
    try:
        data = json.loads(history_file.read_text(encoding="utf-8"))
        return jsonify({"history": data[-50:]})
    except Exception as e:
        return jsonify({"history": [], "error": str(e)})


@app.route("/output/<path:filename>")
def serve_output(filename):
    """Üretilen videoları web üzerinden serve eder (önizleme için)."""
    output_dir = Path("output").resolve()
    file_path = (output_dir / filename).resolve()
    # Güvenlik: path traversal önle
    if not str(file_path).startswith(str(output_dir)):
        abort(403)
    if not file_path.exists():
        abort(404)
    return send_from_directory(output_dir, filename)


# ── Başlangıç hook'u ────────────────────────────────────────────────

_bg_started = False


def _start_background_services():
    """Flask'ın ilk isteği öncesinde bot ve scheduler'ı başlat.
    Çift başlatmayı flag ile önle."""
    global _bg_started
    if _bg_started:
        return
    _bg_started = True

    if os.environ.get("START_TELEGRAM", "1") == "1":
        try:
            start_telegram_bg()
            log.info("Telegram bot thread başlatıldı")
        except Exception as e:
            log.warning(f"Telegram başlatılamadı: {e}")

    if os.environ.get("START_SCHEDULER", "1") == "1":
        try:
            start_scheduler()
            log.info("Scheduler başlatıldı")
        except Exception as e:
            log.warning(f"Scheduler başlatılamadı: {e}")


# Flask 3.x: before_first_request kaldırıldı, onun yerine bu desen:
@app.before_request
def ensure_bg_started():
    _start_background_services()


if __name__ == "__main__":
    _start_background_services()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
