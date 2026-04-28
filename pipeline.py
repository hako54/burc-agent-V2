"""
Pipeline Orchestrator (Çoklu Kanal + Çoklu İçerik Tipi)
Kanal bazında, içerik tipi bazında üretim yönetir.

Genel akış:
1. Kanaldan content_type belirle (zodiac, motivation, ...)
2. module.build_prompt() → LLM'e gönder
3. LLM JSON → post-process (imla)
4. render_video (görsel + TTS + montaj)
5. YouTube'a yükle (veya onay kuyruğuna al)
"""

import os
import json
import logging
import re
from pathlib import Path
from datetime import datetime

from services.content import call_llm_with_fallback, parse_llm_json
from services.video import render_video
from services.youtube import upload_video
from services.text_cleaner import clean_content
import job_tracker as jt
import approval
import channel_registry as ch_registry
import channel_modules
import cancel_manager as cancel_mgr

log = logging.getLogger(__name__)


def _tg_notify(text: str):
    try:
        from telegram_bot import send as tg_send
        tg_send(text)
    except Exception as e:
        log.warning(f"Telegram notify hata: {e}")


DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output"))


def _channel_dir(channel_id: str) -> Path:
    path = DATA_DIR / channel_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _history_file(channel_id: str) -> Path:
    return _channel_dir(channel_id) / "history.json"


def _themes_file(channel_id: str) -> Path:
    return _channel_dir(channel_id) / "used_themes.json"


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


def _get_used_themes(topic_key: str, channel_id: str) -> list:
    all_themes = _load_json(_themes_file(channel_id), {})
    return [t["theme"] for t in all_themes.get(topic_key, [])][-20:]


def _save_used_theme(topic_key: str, theme: str, channel_id: str):
    path = _themes_file(channel_id)
    all_themes = _load_json(path, {})
    all_themes.setdefault(topic_key, []).append({
        "theme": theme,
        "date": datetime.now().isoformat(),
    })
    all_themes[topic_key] = all_themes[topic_key][-50:]
    _save_json(path, all_themes)


def _save_to_history(entry: dict, channel_id: str):
    path = _history_file(channel_id)
    history = _load_json(path, [])
    history.append(entry)
    history = history[-500:]
    _save_json(path, history)


def _job_key(channel_id: str, topic_key: str) -> str:
    """Job tracker için kanal bazlı anahtar."""
    return f"{channel_id}:{topic_key}"


# ── Ana Üretim Fonksiyonu ────────────────────────────────────────

def produce_content(
    channel_id: str,
    topic_key: str,
    custom_topic: str = None,
    upload: bool = True,
    source: str = "web",
    scheduled_publish_at: str = None,
    require_approval: bool = False,
) -> dict:
    """Bir kanala bir içerik üretir.

    Args:
        channel_id: Hangi kanala
        topic_key: Hangi konu/kategori (burç adı, motivasyon kategorisi vs.)
        custom_topic: Serbest metin konu (manuel mod)
        upload: YouTube'a yüklensin mi
        source: 'web', 'telegram', 'scheduler'
        scheduled_publish_at: YouTube planlı yayın
        require_approval: Onay kuyruğuna alsın mı
    """
    channel = ch_registry.get_channel(channel_id)
    if not channel:
        raise ValueError(f"Kanal bulunamadı: {channel_id}")

    module = channel_modules.load_module(channel["id"], channel.get("type", "zodiac"))
    topic_key = (topic_key or "").lower().strip()

    log.info("=" * 60)
    log.info(f"🎬 {channel['name']} ({channel['type']}) üretim başlıyor")
    log.info(f"   Konu: {topic_key}" + (f" ({custom_topic})" if custom_topic else ""))
    log.info(f"   Kaynak: {source}")

    jkey = _job_key(channel_id, topic_key)

    if source == "web":
        _tg_notify(
            f"🌐 <b>Panelden üretim başladı</b>\n"
            f"{channel.get('icon', '📺')} <b>{channel['name']}</b> · {topic_key}"
        )

    if not jt.get_job(jkey) or not jt.is_running(jkey):
        jt.start_job(jkey, source=source)

    # Cancel event kaydet
    cancel_mgr.register_job(jkey)

    # Voice config'ı kanaldan al
    voice_config = {
        "voice_id": channel.get("voice_id"),
        "stability": channel.get("voice_stability", 0.50),
        "style": channel.get("voice_style", 0.35),
        "speed": channel.get("voice_speed", 0.95),
    }

    try:
        # 1) Prompt hazırla ve LLM çağır
        cancel_mgr.check_is_cancelled(jkey)
        jt.update_stage(jkey, jt.STAGE_CONTENT)
        used_themes = _get_used_themes(topic_key, channel_id)
        prompt = module.build_prompt(
            topic_key=topic_key,
            custom_topic=custom_topic,
            used_themes=used_themes,
        )
        raw, provider = call_llm_with_fallback(prompt)
        cancel_mgr.record_llm_call(jkey, chars_in=len(prompt),
                                   chars_out=len(raw))
        content = parse_llm_json(raw)
        content = clean_content(content)

        jt.set_provider(jkey, provider)
        jt.set_title(jkey, content.get("title", ""))

        _save_used_theme(
            topic_key,
            content.get("theme", content.get("title", "")),
            channel_id,
        )

        # Content_type'a özgü meta bilgileri zenginleştir
        theme_colors = module.get_theme_colors(topic_key, content)
        content["accent_color"] = theme_colors["accent_color"]
        content["background_color"] = theme_colors["background_color"]
        content["pexels_queries"] = module.get_visual_queries(topic_key, content)
        content["topic_key"] = topic_key
        content["topic_label"] = _topic_label(module, topic_key)
        content["intro_text"] = module.get_intro_text(topic_key, content)
        content["outro_text"] = module.get_outro_text(topic_key, content)
        content["lucky_card"] = module.get_lucky_card(topic_key, content)

        # Video template meta bilgileri — video.py bunları okur
        # Motivasyon: kategori adı ve icon, Burç: sign_name + sembol
        meta = getattr(module, "CHANNEL_META", {})
        type_id = meta.get("type_id", "zodiac")

        if type_id == "zodiac":
            # Burç için mevcut sistem — LLM zaten sign_name/sign_symbol dolduruyor
            content["intro_subtitle"] = "Günlük Burç Yorumu"
            content["outro_subtitle"] = "Her gün yeni burç yorumu"
        elif type_id == "motivation":
            # Motivasyon için topic meta bilgilerini intro'ya yerleştir
            topics = module.get_topics()
            topic = next((t for t in topics if t["key"] == topic_key), None)
            if topic:
                # Hazır kategori
                content["main_label"] = topic["name"]
                content["main_icon"] = topic.get("emoji",
                                                 topic.get("icon", "✨"))
                # Kadın yüzü thumbnail için face_queries
                from channel_modules.motivasyon.config import CATEGORIES
                cat = CATEGORIES.get(topic_key, {})
                content["face_queries"] = cat.get("face_queries", [])
            elif custom_topic:
                # Kullanıcı yazdığı özel konu — başlığı normalize et
                ct = custom_topic.strip()
                if len(ct) > 30:
                    ct = ct[:30].rsplit(" ", 1)[0] + "..."
                content["main_label"] = ct.title()
                content["main_icon"] = "✨"
                # Custom için generic kadın yüzü
                content["face_queries"] = [
                    "woman portrait emotional close up",
                    "woman face thoughtful soft light",
                    "woman portrait expressive",
                ]
            else:
                content["main_label"] = topic_key.title()
                content["main_icon"] = "✨"
                content["face_queries"] = ["woman portrait expressive"]
            content["intro_subtitle"] = "Bugün İçin"
            content["outro_subtitle"] = "Her gün dünyaya farklı bak"
            content["sign_name"] = ""
            content["sign_symbol"] = ""
            content["lucky_number"] = ""
            content["lucky_color"] = ""
            content["compatible_sign"] = ""
        else:
            content["intro_subtitle"] = meta.get("type_name", "Günlük İçerik")
            content["outro_subtitle"] = "Her gün yeni içerik"

        content["provider"] = provider
        content["generated_at"] = datetime.now().isoformat()

        # 2a) Thumbnail üret (önce — render'da intro için kullanılabilsin)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = re.sub(r"[^a-z0-9\-]", "-", topic_key.lower())[:20] or "content"
        video_path = str(OUTPUT_DIR / f"{channel_id}_{safe_topic}_{ts}.mp4")
        thumbnail_path = video_path.replace(".mp4", "_thumb.jpg")
        intro_face_path = video_path.replace(".mp4", "_intro.jpg")
        try:
            from services.thumbnail import generate_thumbnail
            type_id = channel.get("type", "zodiac")
            # YouTube için yatay thumbnail
            generate_thumbnail(content, thumbnail_path,
                               channel_type=type_id, vertical=False)
            # Motivasyon için dikey kadın yüzü intro'da kullanılır
            if type_id == "motivation":
                generate_thumbnail(content, intro_face_path,
                                   channel_type=type_id, vertical=True)
                if os.path.exists(intro_face_path):
                    content["intro_face_image"] = intro_face_path
        except Exception as e:
            log.warning(f"Thumbnail üretilemedi: {e}")
            thumbnail_path = None

        # 2b) Video render
        cancel_mgr.check_is_cancelled(jkey)
        cancel_mgr.mark_render_started(jkey)
        render_video(content, video_path, sign_key=jkey,
                     voice_config=voice_config)

        result = {
            "channel_id": channel_id,
            "channel_name": channel["name"],
            "topic_key": topic_key,
            "topic_label": content.get("topic_label", topic_key),
            "title": content.get("title", ""),
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
            "provider": provider,
            "generated_at": datetime.now().isoformat(),
            "source": source,
            "sign_key": topic_key,  # geriye uyumluluk
        }

        # 3a) Onay gerekliyse kuyruğa al
        if require_approval and upload:
            # Thumbnail path'i content'e de ekle ki approval saklasın
            content["_thumbnail_path"] = thumbnail_path
            approval.add_pending(topic_key, video_path, content, source=source,
                                 channel_id=channel_id)
            result["status"] = "pending_approval"
            result["awaiting_approval"] = True
            _save_to_history(result, channel_id=channel_id)
            jt.finish_job(jkey, result=result)
            cancel_mgr.cleanup_job(jkey)
            log.info(f"⏸ {channel['name']}/{topic_key} onay bekliyor")

            if source == "web":
                _tg_notify(
                    f"🌐 <b>Panelden üretildi — onay bekliyor</b>\n"
                    f"{channel.get('icon', '📺')} <b>{channel['name']}</b>\n"
                    f"📝 {content.get('title', '')[:80]}\n"
                    f"🤖 {provider}\n\nPanelden yayınla/iptal."
                )
            return result

        # 3b) YouTube upload
        if upload:
            cancel_mgr.check_is_cancelled(jkey)
            cancel_mgr.mark_upload_started(jkey)
            jt.update_stage(jkey, jt.STAGE_UPLOAD)

            title = module.format_title(topic_key, content)
            description = module.format_description(topic_key, content)
            tags = module.get_tags(topic_key, content)

            upload_result = upload_video(
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                category_id="22",
                privacy="public",
                scheduled_time=scheduled_publish_at,
                channel_id=channel_id,
                thumbnail_path=thumbnail_path,
            )
            result["youtube_id"] = upload_result["id"]
            result["youtube_url"] = upload_result["url"]

            if source == "web":
                _tg_notify(
                    f"🌐 <b>Panelden yayınlandı</b>\n"
                    f"{channel.get('icon', '📺')} <b>{channel['name']}</b>\n"
                    f"📝 {content.get('title', '')[:80]}\n"
                    f"🔗 {upload_result['url']}"
                )

        _save_to_history(result, channel_id=channel_id)
        jt.finish_job(jkey, result=result)
        cancel_mgr.cleanup_job(jkey)
        log.info(f"🎉 {channel['name']}/{topic_key} tamamlandı\n")
        return result

    except cancel_mgr.JobCancelled:
        log.info(f"⛔ {channel['name']}/{topic_key} iptal edildi")
        report = cancel_mgr.get_resource_report(jkey)
        jt.finish_job(jkey, error="İptal edildi")
        cancel_mgr.cleanup_job(jkey)

        # Kullanıcıya bildir
        if source in ("web", "telegram"):
            summary = "\n".join(report.get("summary_lines", []))
            cost = report.get("estimated_cost_usd", 0) if report else 0
            _tg_notify(
                f"⛔ <b>İptal edildi</b>\n"
                f"{channel.get('icon', '📺')} {channel['name']} / {topic_key}\n"
                f"💸 Harcanan: ~${cost:.3f}\n"
                f"{summary}"
            )
        raise

    except Exception as e:
        log.exception(f"❌ {channel['name']}/{topic_key} başarısız")
        jt.finish_job(jkey, error=str(e))
        cancel_mgr.cleanup_job(jkey)
        if source == "web":
            _tg_notify(
                f"🌐 <b>Panelden üretim hatası</b>\n"
                f"{channel.get('icon', '📺')} {channel['name']}: {str(e)[:150]}"
            )
        raise


def _topic_label(module, topic_key: str) -> str:
    for t in module.get_topics():
        if t["key"] == topic_key:
            return t["name"]
    return topic_key


# ── Onay akışı ────────────────────────────────────────────────────

def approve_and_upload(topic_key: str, channel_id: str = "burc",
                       source: str = "telegram") -> dict:
    """Onay bekleyen videoyu YouTube'a yükler."""
    channel = ch_registry.get_channel(channel_id)
    if not channel:
        raise ValueError(f"Kanal bulunamadı: {channel_id}")

    module = channel_modules.load_module(channel["id"], channel.get("type", "zodiac"))
    topic_key = (topic_key or "").lower().strip()

    pending = approval.get_pending(topic_key, channel_id=channel_id)
    if not pending:
        raise ValueError(f"{topic_key} için onay bekleyen video yok.")

    video_path = pending["video_path"]
    if not os.path.exists(video_path):
        approval.remove_pending(topic_key, channel_id=channel_id)
        raise FileNotFoundError(f"Video dosyası bulunamadı: {video_path}")

    jkey = _job_key(channel_id, topic_key)
    jt.start_job(jkey, source=source)
    jt.update_stage(jkey, jt.STAGE_UPLOAD)

    try:
        # Pending kaydından gerekli bilgileri al
        fake_content = {
            "title": pending.get("title", ""),
            "description": pending.get("description", ""),
            "tags": pending.get("tags", []),
            "hashtags": pending.get("hashtags", []),
        }
        title = module.format_title(topic_key, fake_content)
        description = module.format_description(topic_key, fake_content)
        tags = module.get_tags(topic_key, fake_content)

        upload_result = upload_video(
            video_path=video_path, title=title, description=description,
            tags=tags, category_id="22", privacy="public",
            channel_id=channel_id,
            thumbnail_path=pending.get("thumbnail_path") or None,
        )

        result = {
            "channel_id": channel_id,
            "channel_name": channel["name"],
            "topic_key": topic_key,
            "title": pending.get("title", ""),
            "video_path": video_path,
            "provider": pending.get("provider", "?"),
            "youtube_id": upload_result["id"],
            "youtube_url": upload_result["url"],
            "generated_at": datetime.now().isoformat(),
            "source": source,
            "approved": True,
            "sign_key": topic_key,
        }

        approval.remove_pending(topic_key, delete_file=False,
                                channel_id=channel_id)
        _save_to_history(result, channel_id=channel_id)
        jt.finish_job(jkey, result=result)
        log.info(f"✅ {channel['name']}/{topic_key} yayında: {upload_result['url']}")

        if source == "web":
            _tg_notify(
                f"🌐 <b>Panelden yayınlandı</b>\n"
                f"{channel.get('icon', '📺')} <b>{channel['name']}</b>\n"
                f"🔗 {upload_result['url']}"
            )
        return result

    except Exception as e:
        log.exception(f"approve_and_upload {channel_id}/{topic_key} hata")
        jt.finish_job(jkey, error=str(e))
        raise


def reject_pending(topic_key: str, channel_id: str = "burc",
                   source: str = "telegram") -> dict:
    topic_key = (topic_key or "").lower().strip()
    item = approval.remove_pending(topic_key, delete_file=True,
                                   channel_id=channel_id)
    if not item:
        raise ValueError(f"{topic_key} için onay bekleyen video yok.")

    if source == "web":
        channel = ch_registry.get_channel(channel_id) or {}
        _tg_notify(
            f"🌐 <b>Panelden iptal</b>\n"
            f"{channel.get('icon', '📺')} {channel.get('name', channel_id)} / {topic_key} silindi."
        )
    return item


# ── Batch üretim ──────────────────────────────────────────────────

def produce_topics(channel_id: str, topic_keys: list,
                   upload: bool = True, source: str = "web",
                   scheduled_publish_at: str = None) -> dict:
    """Bir kanal için birden fazla konu üretir."""
    success, failed = [], []
    for topic_key in topic_keys:
        try:
            result = produce_content(
                channel_id=channel_id, topic_key=topic_key,
                upload=upload, source=source,
                scheduled_publish_at=scheduled_publish_at,
                require_approval=False,
            )
            success.append(result)
        except Exception as e:
            log.exception(f"❌ {channel_id}/{topic_key} başarısız")
            failed.append({"topic_key": topic_key, "error": str(e)})
    log.info(f"🏁 Batch bitti: {len(success)}/{len(topic_keys)} başarılı "
             f"({channel_id})")
    return {"success": success, "failed": failed}


# ── Geriye uyumluluk (eski kod çağırmaya devam ederse) ─────────────

def produce_and_upload(sign_input: str, upload: bool = True,
                       source: str = "web",
                       scheduled_publish_at: str = None,
                       require_approval: bool = False,
                       channel_id: str = "burc") -> dict:
    """Eski burç fonksiyonu — zodiac kanalı için."""
    from zodiac import normalize_sign
    normalized = normalize_sign(sign_input)
    if not normalized:
        raise ValueError(f"Geçersiz burç: '{sign_input}'")
    return produce_content(
        channel_id=channel_id, topic_key=normalized,
        upload=upload, source=source,
        scheduled_publish_at=scheduled_publish_at,
        require_approval=require_approval,
    )


def produce_signs(sign_keys: list, upload: bool = True,
                  source: str = "web",
                  scheduled_publish_at: str = None,
                  channel_id: str = "burc") -> dict:
    """Eski batch fonksiyonu — zodiac için."""
    return produce_topics(
        channel_id=channel_id, topic_keys=sign_keys,
        upload=upload, source=source,
        scheduled_publish_at=scheduled_publish_at,
    )


def produce_all_signs(upload: bool = True, source: str = "web",
                      scheduled_publish_at: str = None,
                      channel_id: str = "burc") -> dict:
    from zodiac import all_sign_keys
    return produce_signs(all_sign_keys(), upload=upload, source=source,
                         scheduled_publish_at=scheduled_publish_at,
                         channel_id=channel_id)
