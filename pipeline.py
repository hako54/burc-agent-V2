"""
Pipeline Orchestrator
Tek bir burç için tüm akışı yönetir:
1. İçerik üretimi (Claude/Gemini/Groq)
2. Video render (MoviePy)
3. YouTube upload

Ayrıca geçmişi (`data/history.json`) ve kullanılan temaları tutar.
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
    """Bu burç için son kullanılan temaları döner (tekrar önleme)."""
    all_themes = _load_json(THEMES_FILE, {})
    return [t["theme"] for t in all_themes.get(sign_key, [])][-20:]


def _save_used_theme(sign_key: str, theme: str):
    all_themes = _load_json(THEMES_FILE, {})
    all_themes.setdefault(sign_key, []).append({
        "theme": theme,
        "date": datetime.now().isoformat(),
    })
    # Her burç için son 50 tema
    all_themes[sign_key] = all_themes[sign_key][-50:]
    _save_json(THEMES_FILE, all_themes)


def _save_to_history(entry: dict):
    history = _load_json(HISTORY_FILE, [])
    history.append(entry)
    # Son 500 kayıt
    history = history[-500:]
    _save_json(HISTORY_FILE, history)


def produce_and_upload(sign_input: str, upload: bool = True) -> dict:
    """Bir burç için tam akış: içerik üret, video render et, YouTube'a yükle.

    Args:
        sign_input: Burç adı (koc/koç/aries hepsi kabul).
        upload: False verirse sadece video üretir, YouTube'a yüklemez.
                (Web panelinden "önizleme" modu için kullanılabilir.)

    Returns:
        {
            'sign_key': 'koc',
            'title': '...',
            'video_path': '/path/to/video.mp4',
            'youtube_url': 'https://...' (upload=True ise),
            'youtube_id': 'xxx' (upload=True ise),
            'provider': 'Claude' | 'Gemini' | 'Groq',
        }
    """
    sign_key = normalize_sign(sign_input)
    if not sign_key:
        raise ValueError(
            f"Geçersiz burç: '{sign_input}'. "
            f"Geçerli: {', '.join(all_sign_keys())}"
        )

    info = get_sign(sign_key)
    log.info(f"{'='*50}")
    log.info(f"🔮 {info['emoji']} {info['name']} üretim başlıyor")

    # 1) İçerik
    used_themes = _get_used_themes(sign_key)
    content = generate_content(sign_key, used_themes)
    _save_used_theme(sign_key, content.get("theme", content.get("title", "")))

    # 2) Video render
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = str(OUTPUT_DIR / f"burc_{sign_key}_{ts}.mp4")
    render_video(content, video_path)

    result = {
        "sign_key": sign_key,
        "sign_name": info["name"],
        "title": content.get("title", ""),
        "video_path": video_path,
        "provider": content.get("provider", "?"),
        "generated_at": datetime.now().isoformat(),
    }

    # 3) Upload
    if upload:
        # Hashtag'leri açıklamaya ekle
        hashtags = content.get("hashtags", [])
        base_tags = content.get("tags", [])
        extra_tags = [
            "burç", "günlükburç", "astroloji", "shorts", "keşfet",
            info["name"].lower(), f"{info['name'].lower()}burcu",
        ]
        all_tags = list(dict.fromkeys(base_tags + extra_tags))[:15]

        base_hashtags = hashtags
        extra_hashtags = [
            f"#{info['name'].lower()}", f"#{info['name'].lower()}burcu",
            "#günlükburç", "#astroloji", "#shorts", "#burç",
            "#zodyak", "#keşfet", "#viral", "#keşfetteyim",
        ]
        all_hashtags = list(dict.fromkeys(base_hashtags + extra_hashtags))[:15]

        description = (
            content.get("description", "")
            + "\n\n" + " ".join(all_hashtags)
        )

        upload_result = upload_video(
            video_path=video_path,
            title=content.get("title", f"{info['name']} Günlük Yorum"),
            description=description,
            tags=all_tags,
            category_id="22",  # People & Blogs
            privacy="public",
        )

        result["youtube_id"] = upload_result["id"]
        result["youtube_url"] = upload_result["url"]

    _save_to_history(result)
    log.info(f"🎉 {info['name']} tamamlandı\n")
    return result


def produce_all_signs(upload: bool = True) -> dict:
    """12 burcun hepsini sırayla üretir ve yükler.

    Returns:
        {'success': [...], 'failed': [...]}
    """
    success = []
    failed = []

    for sign_key in all_sign_keys():
        try:
            result = produce_and_upload(sign_key, upload=upload)
            success.append(result)
        except Exception as e:
            log.exception(f"❌ {sign_key} başarısız")
            failed.append({"sign_key": sign_key, "error": str(e)})

    log.info(f"🏁 Toplu üretim bitti: {len(success)}/12 başarılı")
    return {"success": success, "failed": failed}
