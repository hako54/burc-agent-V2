"""
Flask Web Uygulaması (Çoklu Kanal)

Sayfa yapısı:
- /                   → Giriş sayfası, kanal seçici
- /channel/<id>       → Belirli bir kanalın paneli
- /admin/channels     → Kanal yönetimi (ekle/sil/düzenle)

API endpoint'leri kanal bazında çalışır:
  /api/<channel_id>/signs
  /api/<channel_id>/produce/<sign>
  /api/<channel_id>/approve/<sign>
  /api/<channel_id>/history
  /api/<channel_id>/youtube/recent
"""

import os
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from flask import (
    Flask, render_template, jsonify, request,
    send_from_directory, abort, redirect, url_for
)

import bootstrap
bootstrap.setup_all()

from zodiac import ZODIAC_SIGNS, normalize_sign, get_sign, all_sign_keys
from pipeline import produce_and_upload, produce_all_signs
from telegram_bot import start_background as start_telegram_bg
from scheduler import start_scheduler
import job_tracker as jt
import channel_registry as ch_registry
import channel_modules
import approval

log = logging.getLogger(__name__)

app = Flask(__name__)

# Batch iş durumu — kanal bazlı
_batch_state = {}
_batch_lock = threading.Lock()


# ── Sayfalar ──────────────────────────────────────────────────────

@app.route("/")
def index():
    """Giriş sayfası — kanal seçici."""
    return render_template("landing.html")


@app.route("/channel/<channel_id>")
def channel_panel(channel_id):
    """Belirli bir kanalın paneli."""
    channel = ch_registry.get_channel(channel_id)
    if not channel:
        return redirect(url_for("index"))
    return render_template("dashboard.html", channel=channel)


@app.route("/admin/channels")
def admin_channels():
    """Kanal yönetim sayfası."""
    return render_template("channels_admin.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


# ── Kanal Yönetimi API ────────────────────────────────────────────

@app.route("/api/channels")
def api_channels():
    """Tüm kanalları listele."""
    return jsonify({
        "channels": ch_registry.list_channels(),
        "types": ch_registry.CHANNEL_TYPES,
    })


@app.route("/api/channels", methods=["POST"])
def api_channel_create():
    """Yeni kanal ekle."""
    data = request.get_json() or {}
    try:
        channel = ch_registry.add_channel(
            channel_id=data.get("id", "").strip(),
            name=data.get("name", "").strip(),
            channel_type=data.get("type", "zodiac"),
            youtube_url=data.get("youtube_url", "").strip(),
            color=data.get("color", "#d4af37"),
        )
        return jsonify({"channel": channel, "status": "created"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/channels/<channel_id>", methods=["PUT"])
def api_channel_update(channel_id):
    """Kanal bilgilerini güncelle (name, youtube_url, color, voice_*)."""
    data = request.get_json() or {}
    try:
        channel = ch_registry.update_channel(
            channel_id,
            name=data.get("name"),
            youtube_url=data.get("youtube_url"),
            color=data.get("color"),
            voice_id=data.get("voice_id"),
            voice_stability=data.get("voice_stability"),
            voice_style=data.get("voice_style"),
            voice_speed=data.get("voice_speed"),
        )
        return jsonify({"channel": channel})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/voices")
def api_voices():
    """Sesleri 3 kaynaktan toplar:
    1. Önerilen Türkçe-uyumlu ElevenLabs sesleri (hardcoded)
    2. Kullanıcının ElevenLabs hesabındaki özel sesler (API'den)
    3. Kullanıcının manuel eklediği sesler (data/custom_voices.json)
    """
    # 1) Hardcoded öneri listesi
    recommended = [
        {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",
         "description": "Sıcak anlatımcı, kadın", "gender": "female",
         "source": "recommended"},
        {"id": "XB0fDUnXU5powFXDhCwa", "name": "Charlotte",
         "description": "Sakin, mistik, kadın", "gender": "female",
         "source": "recommended"},
        {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella",
         "description": "Yumuşak, genç kadın", "gender": "female",
         "source": "recommended"},
        {"id": "9BWtsMINqrJLrRacOk9x", "name": "Aria",
         "description": "Duygusal, empatik", "gender": "female",
         "source": "recommended"},
        {"id": "XrExE9yKIg1WjnnlVkGX", "name": "Matilda",
         "description": "Tatlı, naif", "gender": "female",
         "source": "recommended"},
        {"id": "pFZP5JQG7iQjIQuC4Bku", "name": "Lily",
         "description": "Sıcak, genç", "gender": "female",
         "source": "recommended"},
        {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi",
         "description": "Güçlü, kararlı", "gender": "female",
         "source": "recommended"},
        {"id": "ThT5KcBeYPX3keUQqHPh", "name": "Dorothy",
         "description": "Olgun, sakin", "gender": "female",
         "source": "recommended"},
        {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam",
         "description": "Derin, anlatımcı", "gender": "male",
         "source": "recommended"},
        {"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold",
         "description": "Vurgulu, etkileyici", "gender": "male",
         "source": "recommended"},
        {"id": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam",
         "description": "Genç, dinamik", "gender": "male",
         "source": "recommended"},
        {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh",
         "description": "Sıcak, anlatımcı erkek", "gender": "male",
         "source": "recommended"},
        {"id": "onwK4e9ZLuTAKqWW03F9", "name": "Daniel",
         "description": "Profesyonel, ciddi", "gender": "male",
         "source": "recommended"},
    ]

    # 2) ElevenLabs hesabından çek (API key ile)
    elevenlabs_voices = []
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if api_key:
        try:
            import requests
            r = requests.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key},
                timeout=10, verify=False,
            )
            if r.status_code == 200:
                voices_resp = r.json().get("voices", [])
                recommended_ids = {v["id"] for v in recommended}
                for v in voices_resp:
                    vid = v.get("voice_id")
                    if not vid or vid in recommended_ids:
                        continue
                    labels = v.get("labels", {}) or {}
                    elevenlabs_voices.append({
                        "id": vid,
                        "name": v.get("name", "(adsız)"),
                        "description": labels.get("description")
                                       or labels.get("description_short")
                                       or labels.get("accent", "")
                                       or "ElevenLabs hesabından",
                        "gender": labels.get("gender", "unknown"),
                        "source": "elevenlabs",
                        "category": v.get("category", ""),
                    })
        except Exception as e:
            log.warning(f"ElevenLabs voices fetch hata: {e}")

    # 3) Custom (kullanıcının manuel eklediği)
    custom_voices = _load_custom_voices()

    return jsonify({
        "voices": recommended + custom_voices + elevenlabs_voices,
        "recommended_count": len(recommended),
        "elevenlabs_count": len(elevenlabs_voices),
        "custom_count": len(custom_voices),
    })


def _custom_voices_file():
    return Path(os.environ.get("DATA_DIR", "data")) / "custom_voices.json"


def _load_custom_voices() -> list:
    p = _custom_voices_file()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_custom_voices(voices: list):
    p = _custom_voices_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(voices, ensure_ascii=False, indent=2),
                 encoding="utf-8")


@app.route("/api/voices/custom", methods=["POST"])
def api_voice_add_custom():
    """Manuel ses ekle.
    Body: {"id": "voice_id", "name": "...", "description": "...", "gender": "..."}
    """
    data = request.get_json() or {}
    vid = (data.get("id") or "").strip()
    name = (data.get("name") or "").strip()
    if not vid or not name:
        return jsonify({"error": "id ve name zorunlu"}), 400

    voices = _load_custom_voices()
    if any(v["id"] == vid for v in voices):
        return jsonify({"error": "Bu Voice ID zaten ekli"}), 400

    new_voice = {
        "id": vid,
        "name": name,
        "description": (data.get("description") or "Özel").strip(),
        "gender": data.get("gender", "unknown"),
        "source": "custom",
    }
    voices.append(new_voice)
    _save_custom_voices(voices)
    return jsonify({"voice": new_voice, "status": "added"})


@app.route("/api/voices/custom/<voice_id>", methods=["DELETE"])
def api_voice_delete_custom(voice_id):
    voices = _load_custom_voices()
    new_voices = [v for v in voices if v["id"] != voice_id]
    if len(new_voices) == len(voices):
        return jsonify({"error": "Ses bulunamadı"}), 404
    _save_custom_voices(new_voices)
    return jsonify({"status": "deleted"})


@app.route("/api/<channel_id>/batch", methods=["POST"])
def api_channel_batch(channel_id):
    """Manuel batch üretimi başlatır.
    Body: {
      "group": "today" | "tomorrow" | "all",
      "require_approval": false (varsayılan)
    }
    """
    channel = ch_registry.get_channel(channel_id)
    if not channel:
        return jsonify({"error": "Kanal bulunamadı"}), 404

    if channel.get("type") != "zodiac":
        return jsonify({
            "error": "Batch sadece zodiac (burç) kanallarında çalışır"
        }), 400

    data = request.get_json(silent=True) or {}
    group_type = data.get("group", "today")
    require_approval = bool(data.get("require_approval", False))

    from zodiac import (get_todays_group, GROUP_EVEN_DAYS,
                        GROUP_ODD_DAYS, all_sign_keys)
    from datetime import datetime as _dt, timedelta

    if group_type == "today":
        topic_keys = get_todays_group()
        label = "Bugünün 6 burcu"
    elif group_type == "tomorrow":
        # Yarın çift mi tek mi?
        tomorrow_day = (_dt.now() + timedelta(days=1)).day
        topic_keys = (GROUP_EVEN_DAYS if tomorrow_day % 2 == 0
                      else GROUP_ODD_DAYS)
        label = "Yarının 6 burcu"
    elif group_type == "all":
        topic_keys = all_sign_keys()
        label = "12 burç"
    else:
        return jsonify({"error": "Geçersiz grup"}), 400

    def run():
        try:
            from pipeline import produce_topics
            log.info(f"Manuel batch başladı: {label} ({channel_id})")
            results = produce_topics(
                channel_id=channel_id,
                topic_keys=topic_keys,
                upload=True,
                source="web",
                scheduled_publish_at=None,
            )
            try:
                from telegram_bot import send as tg_send
                s = len(results["success"])
                f = len(results["failed"])
                tg_send(
                    f"🌐 <b>Manuel batch tamamlandı</b>\n"
                    f"📺 {channel.get('name')}\n"
                    f"✅ {s}/{len(topic_keys)} başarılı"
                    + (f"\n❌ {f} başarısız" if f else "")
                )
            except Exception:
                pass
        except Exception as e:
            log.exception(f"Manuel batch {channel_id} hata")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({
        "channel_id": channel_id,
        "group": group_type,
        "topics": topic_keys,
        "label": label,
        "status": "running",
    })


@app.route("/api/<channel_id>/group-info")
def api_channel_group_info(channel_id):
    """Bugün/yarın hangi grup üretiliyor öğren."""
    from zodiac import (get_todays_group, GROUP_EVEN_DAYS,
                        GROUP_ODD_DAYS, get_sign)
    from datetime import datetime as _dt, timedelta

    today = _dt.now()
    tomorrow = today + timedelta(days=1)

    today_group = get_todays_group()
    tomorrow_keys = (GROUP_EVEN_DAYS if tomorrow.day % 2 == 0
                     else GROUP_ODD_DAYS)

    def keys_to_meta(keys):
        return [
            {"key": k, "name": get_sign(k)["name"],
             "symbol": get_sign(k)["symbol"]}
            for k in keys
        ]

    return jsonify({
        "today": {
            "date": today.strftime("%d %B %Y"),
            "day_type": "ÇİFT" if today.day % 2 == 0 else "TEK",
            "keys": today_group,
            "topics": keys_to_meta(today_group),
        },
        "tomorrow": {
            "date": tomorrow.strftime("%d %B %Y"),
            "day_type": "ÇİFT" if tomorrow.day % 2 == 0 else "TEK",
            "keys": tomorrow_keys,
            "topics": keys_to_meta(tomorrow_keys),
        },
    })


@app.route("/api/voice-test", methods=["POST"])
def api_voice_test():
    """Verilen voice config ile kısa bir test sesi üretir.
    Body: {"voice_id": "...", "stability": 0.5, "style": 0.4, "speed": 1.0,
           "text": "test metni" (opsiyonel)}
    Dönüş: dosya URL'si"""
    data = request.get_json() or {}
    voice_id = data.get("voice_id", "21m00Tcm4TlvDq8ikWAM")
    text = data.get("text") or (
        "Merhaba, bu bir ses testidir. "
        "Bugün kendine iyi davranmayı unutma."
    )

    voice_config = {
        "voice_id": voice_id,
        "stability": float(data.get("stability", 0.50)),
        "style": float(data.get("style", 0.35)),
        "speed": float(data.get("speed", 0.95)),
        "similarity_boost": 0.75,
    }

    try:
        from services.tts import generate_tts
        # Output dizinine geçici dosya
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
        filename = f"voice_test_{ts}.mp3"
        out_path = str(Path(os.environ.get("OUTPUT_DIR", "output")) / filename)
        generate_tts(text, out_path, voice_config=voice_config)
        return jsonify({
            "ok": True,
            "url": f"/output/{filename}",
            "filename": filename,
        })
    except Exception as e:
        log.exception("Voice test hata")
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/api/channels/<channel_id>", methods=["DELETE"])
def api_channel_delete(channel_id):
    try:
        channel = ch_registry.remove_channel(channel_id)
        return jsonify({"channel": channel, "status": "deleted"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── Kanal Bazlı Üretim API ────────────────────────────────────────

@app.route("/api/<channel_id>/signs")
def api_channel_signs(channel_id):
    """Kanal detayı + konu listesi (content_type'a göre)."""
    channel = ch_registry.get_channel(channel_id)
    if not channel:
        return jsonify({"error": "Kanal bulunamadı"}), 404

    module = channel_modules.load_module(channel["id"],
                                         channel.get("type", "zodiac"))
    topics = module.get_topics()
    meta = module.CHANNEL_META

    signs = [
        {
            "key": t["key"],
            "name": t["name"],
            "symbol": t.get("icon", t.get("emoji", "✨")),
            "emoji": t.get("emoji", t.get("icon", "✨")),
            "element": t.get("meta", ""),
            "dates": t.get("subtitle", ""),
            "color": t.get("color", "#d4af37"),
        }
        for t in topics
    ]
    return jsonify({
        "channel": channel,
        "signs": signs,
        "topics": topics,
        "content_type": {
            "id": meta["type_id"],
            "name": meta["type_name"],
            "icon": meta["icon"],
            "supports_manual": meta.get("supports_manual", True),
            "supports_auto": meta.get("supports_auto", False),
        },
    })


@app.route("/api/<channel_id>/produce/<sign_key>", methods=["POST"])
def api_channel_produce(channel_id, sign_key):
    """Belirli kanala bir konu video üretimi başlat.
    Body: {"upload": bool, "require_approval": bool, "custom_topic": str}
    """
    channel = ch_registry.get_channel(channel_id)
    if not channel:
        return jsonify({"error": "Kanal bulunamadı"}), 404

    key = (sign_key or "").lower().strip()
    if not key:
        return jsonify({"error": "Konu anahtarı eksik"}), 400

    data = request.get_json(silent=True) or {}
    upload = bool(data.get("upload", True))
    require_approval = bool(data.get("require_approval", True))
    custom_topic = (data.get("custom_topic") or "").strip() or None

    job_key = f"{channel_id}:{key}"
    if jt.is_running(job_key):
        return jsonify({
            "error": "Bu kanal + konu için işlem zaten çalışıyor",
            "job": jt.get_job(job_key),
        }), 409

    jt.start_job(job_key, source="web")

    def run():
        try:
            from pipeline import produce_content
            produce_content(
                channel_id=channel_id, topic_key=key,
                custom_topic=custom_topic,
                upload=upload, source="web",
                require_approval=require_approval,
            )
        except Exception as e:
            log.exception(f"Web job {channel_id}/{key} hata")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({
        "channel_id": channel_id,
        "sign_key": key,
        "status": "running",
        "require_approval": require_approval,
    })


@app.route("/api/<channel_id>/cancel/<sign_key>", methods=["POST"])
def api_channel_cancel(channel_id, sign_key):
    """Çalışan bir üretimi iptal eder."""
    import cancel_manager
    key = (sign_key or "").lower().strip()
    job_key = f"{channel_id}:{key}"
    cancelled = cancel_manager.cancel_job(job_key)
    report = cancel_manager.get_resource_report(job_key)
    return jsonify({
        "cancelled": cancelled,
        "sign_key": key,
        "channel_id": channel_id,
        "report": report,
    })


@app.route("/api/<channel_id>/resources/<sign_key>")
def api_channel_resources(channel_id, sign_key):
    """O an harcanan kaynakların özeti."""
    import cancel_manager
    key = (sign_key or "").lower().strip()
    job_key = f"{channel_id}:{key}"
    return jsonify({"report": cancel_manager.get_resource_report(job_key)})


@app.route("/api/<channel_id>/approve/<sign_key>", methods=["POST"])
def api_channel_approve(channel_id, sign_key):
    from pipeline import approve_and_upload
    key = (sign_key or "").lower().strip()
    if not key:
        return jsonify({"error": "Konu eksik"}), 400

    def run():
        try:
            approve_and_upload(topic_key=key, channel_id=channel_id,
                               source="web")
        except Exception as e:
            log.exception(f"Approve {channel_id}/{key} hata")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"sign_key": key, "channel_id": channel_id,
                    "status": "uploading"})


@app.route("/api/<channel_id>/reject/<sign_key>", methods=["POST"])
def api_channel_reject(channel_id, sign_key):
    from pipeline import reject_pending
    key = (sign_key or "").lower().strip()
    if not key:
        return jsonify({"error": "Konu eksik"}), 400
    try:
        reject_pending(topic_key=key, channel_id=channel_id, source="web")
        return jsonify({"sign_key": key, "status": "rejected"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/<channel_id>/pending")
def api_channel_pending(channel_id):
    return jsonify({"pending": approval.list_pending(channel_id=channel_id)})


@app.route("/api/<channel_id>/jobs")
def api_channel_jobs(channel_id):
    """O kanala ait aktif işleri filtrele."""
    prefix = f"{channel_id}:"
    all_jobs = jt.all_jobs()
    channel_jobs = {}
    for key, job in all_jobs.items():
        if key.startswith(prefix):
            sign_only = key[len(prefix):]
            channel_jobs[sign_only] = job
    return jsonify({"jobs": channel_jobs, "batch": _batch_state.get(channel_id, {})})


@app.route("/api/<channel_id>/history")
def api_channel_history(channel_id):
    """Kanal bazlı history."""
    history_file = (Path(os.environ.get("DATA_DIR", "data"))
                    / channel_id / "history.json")
    if not history_file.exists():
        return jsonify({"history": []})
    try:
        data = json.loads(history_file.read_text(encoding="utf-8"))
        data = sorted(data, key=lambda e: e.get("generated_at", ""),
                      reverse=True)
        return jsonify({"history": data[:50]})
    except Exception as e:
        return jsonify({"history": [], "error": str(e)})


@app.route("/api/<channel_id>/youtube/recent")
def api_channel_youtube_recent(channel_id):
    """O kanalın YouTube'dan son videolarını çeker."""
    try:
        from services.youtube import get_youtube_service
        yt = get_youtube_service(channel_id=channel_id)

        ch_resp = yt.channels().list(part="snippet,contentDetails",
                                     mine=True).execute()
        if not ch_resp.get("items"):
            return jsonify({"videos": []})

        channel = ch_resp["items"][0]
        uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]

        pl_resp = yt.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
        ).execute()

        videos = []
        for item in pl_resp.get("items", []):
            vid_id = item["contentDetails"]["videoId"]
            snip = item["snippet"]
            videos.append({
                "youtube_id": vid_id,
                "youtube_url": f"https://youtube.com/shorts/{vid_id}",
                "short_url": f"https://youtu.be/{vid_id}",
                "title": snip.get("title", ""),
                "published_at": snip.get("publishedAt", ""),
                "thumbnail": snip.get("thumbnails", {}).get("medium", {}).get("url", ""),
            })
        videos.sort(key=lambda v: v.get("published_at", ""), reverse=True)
        return jsonify({
            "videos": videos,
            "channel_title": channel["snippet"].get("title", ""),
            "channel_url": f"https://youtube.com/channel/{channel['id']}",
        })
    except Exception as e:
        log.exception(f"YouTube recent fetch hata ({channel_id})")
        return jsonify({"videos": [], "error": str(e)[:200]}), 500


# ── Videoları sun ──────────────────────────────────────────────────

@app.route("/output/<path:filename>")
def serve_output(filename):
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output")).resolve()
    file_path = (output_dir / filename).resolve()
    if not str(file_path).startswith(str(output_dir)):
        abort(403)
    if not file_path.exists():
        abort(404)
    return send_from_directory(output_dir, filename)


# ── Arka plan servisleri ──────────────────────────────────────────

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
