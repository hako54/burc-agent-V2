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
bootstrap.setup_all()  # Ortam hazırlığı burada olmalı

from zodiac import ZODIAC_SIGNS, normalize_sign, get_sign, all_sign_keys
from pipeline import produce_and_upload, produce_all_signs
from telegram_bot import start_background as start_telegram_bg
from scheduler import start_scheduler
import job_tracker as jt

log = logging.getLogger(__name__)

app = Flask(__name__)

# Batch iş için ayrı durum
_batch_state = {"running": False, "started_at": None, "finished_at": None,
                "success_count": 0, "fail_count": 0}
_batch_lock = threading.Lock()


# ── Web Paneli ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


# ── REST API ────────────────────────────────────────────────────────

@app.route("/api/signs")
def api_signs():
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
    """Bir burç için üretim başlatır (arka planda).
    Varsayılan: require_approval=True → video üretilir, onay beklenir.
    Body: {"require_approval": true|false}
    """
    key = normalize_sign(sign_key)
    if not key:
        return jsonify({"error": "Geçersiz burç"}), 400

    data = request.get_json(silent=True) or {}
    upload = bool(data.get("upload", True))
    require_approval = bool(data.get("require_approval", True))

    if jt.is_running(key):
        return jsonify({
            "error": "Bu burç için işlem zaten çalışıyor",
            "job": jt.get_job(key),
        }), 409

    jt.start_job(key, source="web")

    def run():
        try:
            produce_and_upload(
                key, upload=upload, source="web",
                require_approval=require_approval,
            )
        except Exception as e:
            log.exception(f"Web job {key} hata")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({
        "sign_key": key,
        "status": "running",
        "require_approval": require_approval,
    })


@app.route("/api/approve/<sign_key>", methods=["POST"])
def api_approve(sign_key):
    """Onay bekleyen videoyu YouTube'a yükler."""
    from pipeline import approve_and_upload
    key = normalize_sign(sign_key)
    if not key:
        return jsonify({"error": "Geçersiz burç"}), 400

    def run():
        try:
            approve_and_upload(key, source="web")
        except Exception as e:
            log.exception(f"Approve {key} hata")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"sign_key": key, "status": "uploading"})


@app.route("/api/reject/<sign_key>", methods=["POST"])
def api_reject(sign_key):
    """Onay bekleyen videoyu siler."""
    from pipeline import reject_pending
    key = normalize_sign(sign_key)
    if not key:
        return jsonify({"error": "Geçersiz burç"}), 400
    try:
        reject_pending(key)
        return jsonify({"sign_key": key, "status": "rejected"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pending")
def api_pending():
    """Onay bekleyen tüm videoları listeler."""
    import approval
    return jsonify({"pending": approval.list_pending()})


@app.route("/api/produce-all", methods=["POST"])
def api_produce_all():
    """12 burç için batch üretim."""
    data = request.get_json(silent=True) or {}
    upload = bool(data.get("upload", True))

    with _batch_lock:
        if _batch_state["running"]:
            return jsonify({"error": "Batch zaten çalışıyor"}), 409
        _batch_state["running"] = True
        _batch_state["started_at"] = datetime.now().isoformat()
        _batch_state["finished_at"] = None
        _batch_state["success_count"] = 0
        _batch_state["fail_count"] = 0

    def run():
        try:
            results = produce_all_signs(upload=upload, source="web")
            with _batch_lock:
                _batch_state["running"] = False
                _batch_state["finished_at"] = datetime.now().isoformat()
                _batch_state["success_count"] = len(results["success"])
                _batch_state["fail_count"] = len(results["failed"])
        except Exception as e:
            log.exception("Batch hata")
            with _batch_lock:
                _batch_state["running"] = False
                _batch_state["finished_at"] = datetime.now().isoformat()
                _batch_state["error"] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "running"})


@app.route("/api/jobs")
def api_jobs():
    """Aktif ve tamamlanmış tüm işlerin snapshot'ı."""
    return jsonify({
        "jobs": jt.all_jobs(),
        "batch": dict(_batch_state),
    })


@app.route("/api/job/<sign_key>")
def api_job(sign_key):
    """Tek bir burcun güncel durumu."""
    key = normalize_sign(sign_key)
    if not key:
        return jsonify({"error": "Geçersiz burç"}), 400
    job = jt.get_job(key)
    if not job:
        return jsonify({"job": None})
    return jsonify({"job": job})


@app.route("/api/history")
def api_history():
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
    output_dir = Path("output").resolve()
    file_path = (output_dir / filename).resolve()
    if not str(file_path).startswith(str(output_dir)):
        abort(403)
    if not file_path.exists():
        abort(404)
    return send_from_directory(output_dir, filename)


# ── Başlangıç hook'u ────────────────────────────────────────────────

_bg_started = False
_bg_lock = threading.Lock()


def _start_background_services():
    global _bg_started
    with _bg_lock:
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


@app.before_request
def ensure_bg_started():
    _start_background_services()


if __name__ == "__main__":
    _start_background_services()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
