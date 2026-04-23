"""
Pipeline Orchestrator
Tek bir burç için tüm akışı yönetir:
1. İçerik üretimi (Claude/Gemini/Groq)
2. Video render (MoviePy)
3. YouTube upload

İlerleme aşamaları job_tracker'a bildirilir, böylece hem web panel
hem telegram canlı durumu görebilir.
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime

from zodiac import normalize_sign, get_sign, all_sign_keys
from services.content import generate_content
from services.video import render_video
from services.youtube import upload_video
import job_tracker as jt

log = logging.getLogger(__name__)

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
HISTORY_FILE = DATA_DIR / "history.json"
THEMES_FILE = DATA_DIR / "used_themes.json"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _get_used_themes(sign_key: str) -> list:
    all_themes = _load_json(THEMES_FILE, {})
    return [t["theme"] for t in all_themes.get(sign_key, [])][-20:]


def _save_used_theme(sign_key: str, theme: str):
    all_themes = _load_json(THEMES_FILE, {})
    all_themes.setdefault(sign_key, []).append({
        "theme": theme,
        "date": datetime.now().isoformat(),
    })
    all_themes[sign_key] = all_themes[sign_key][-50:]
    _save_json(THEMES_FILE, all_themes)


def _save_to_history(entry: dict):
    history = _load_json(HISTORY_FILE, [])
    history.append(entry)
    history = history[-500:]
    _save_json(HISTORY_FILE, history)


def produce_and_upload(sign_input: str, upload: bool = True,
                       source: str = "web",
                       scheduled_publish_at: str = None) -> dict:
    """Bir burç için tam akış.

    Args:
        sign_input: Burç adı
        upload: False ise yalnızca video üretir, YouTube'a yüklemez
        source: 'web', 'telegram', 'scheduler'
        scheduled_publish_at: ISO 8601 tarih. Verilirse video 'private'
            olarak yüklenir ve YouTube bu saatte otomatik public yapar.
            Örnek: '2026-04-24T10:00:00+03:00'

    Returns:
        sonuç dict'i
    """
    sign_key = normalize_sign(sign_input)
    if not sign_key:
        raise ValueError(
            f"Geçersiz burç: '{sign_input}'. "
            f"Geçerli: {', '.join(all_sign_keys())}"
        )

    info = get_sign(sign_key)
    log.info(f"{'='*50}")
    log.info(f"🔮 {info['emoji']} {info['name']} üretim başlıyor ({source})")

    # Job başlat (zaten başlatılmadıysa)
    if not jt.get_job(sign_key) or not jt.is_running(sign_key):
        jt.start_job(sign_key, source=source)

    try:
        # 1) İçerik üretimi
        jt.update_stage(sign_key, jt.STAGE_CONTENT)
        used_themes = _get_used_themes(sign_key)
        content = generate_content(sign_key, used_themes)
        jt.set_provider(sign_key, content.get("provider", "?"))
        jt.set_title(sign_key, content.get("title", ""))
        _save_used_theme(sign_key, content.get("theme", content.get("title", "")))

        # 2) Video render — içinde aşamalar işaretlenir
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_path = str(OUTPUT_DIR / f"burc_{sign_key}_{ts}.mp4")
        render_video(content, video_path, sign_key=sign_key)

        result = {
            "sign_key": sign_key,
            "sign_name": info["name"],
            "title": content.get("title", ""),
            "video_path": video_path,
            "provider": content.get("provider", "?"),
            "generated_at": datetime.now().isoformat(),
            "source": source,
        }

        # 3) YouTube upload
        if upload:
            jt.update_stage(sign_key, jt.STAGE_UPLOAD)

            hashtags = content.get("hashtags", [])
            base_tags = content.get("tags", [])
            extra_tags = [
                "burç", "günlükburç", "astroloji", "shorts", "keşfet",
                info["name"].lower(), f"{info['name'].lower()}burcu",
            ]
            all_tags = list(dict.fromkeys(base_tags + extra_tags))[:15]

            extra_hashtags = [
                f"#{info['name'].lower()}", f"#{info['name'].lower()}burcu",
                "#günlükburç", "#astroloji", "#shorts", "#burç",
                "#zodyak", "#keşfet", "#viral", "#keşfetteyim",
            ]
            all_hashtags = list(dict.fromkeys(hashtags + extra_hashtags))[:15]

            description = (
                content.get("description", "")
                + "\n\n" + " ".join(all_hashtags)
            )

            upload_result = upload_video(
                video_path=video_path,
                title=content.get("title", f"{info['name']} Günlük Yorum"),
                description=description,
                tags=all_tags,
                category_id="22",
                privacy="public",
                scheduled_time=scheduled_publish_at,
            )
            result["youtube_id"] = upload_result["id"]
            result["youtube_url"] = upload_result["url"]

        _save_to_history(result)
        jt.finish_job(sign_key, result=result)
        log.info(f"🎉 {info['name']} tamamlandı\n")
        return result

    except Exception as e:
        log.exception(f"❌ {info['name']} başarısız")
        jt.finish_job(sign_key, error=str(e))
        raise


def produce_signs(sign_keys: list, upload: bool = True,
                  source: str = "web",
                  scheduled_publish_at: str = None) -> dict:
    """Verilen burç listesi için sırayla üretim yapar.

    Args:
        sign_keys: Üretilecek burç anahtarları listesi
        upload: YouTube'a yükleme yapılsın mı
        source: Tetikleyen kaynak
        scheduled_publish_at: Hepsini bu saatte yayınlanacak şekilde planla
    """
    success = []
    failed = []

    for sign_key in sign_keys:
        try:
            result = produce_and_upload(
                sign_key, upload=upload, source=source,
                scheduled_publish_at=scheduled_publish_at,
            )
            success.append(result)
        except Exception as e:
            log.exception(f"❌ {sign_key} başarısız")
            failed.append({"sign_key": sign_key, "error": str(e)})

    log.info(f"🏁 Grup üretim bitti: {len(success)}/{len(sign_keys)} başarılı")
    return {"success": success, "failed": failed}


def produce_all_signs(upload: bool = True, source: str = "web",
                      scheduled_publish_at: str = None) -> dict:
    """12 burç için batch üretim (hepsi)."""
    return produce_signs(all_sign_keys(), upload=upload, source=source,
                         scheduled_publish_at=scheduled_publish_at)
