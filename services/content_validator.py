"""
services/content_validator.py — LLM'den gelen içeriği doğrular ve
eksik alanları otomatik doldurur.

Bu modül, LLM'in bazen segments alanını boş veya bozuk döndürdüğü
durumlarda videonun yine de üretilebilmesi için fallback sağlar.
"""

import logging
import re

log = logging.getLogger(__name__)


def ensure_valid_content(content: dict, topic_key: str = "") -> dict:
    """LLM'den gelen content dict'ini valide eder, eksikleri doldurur.
    Boş segments varsa full_narration'dan otomatik segment üretir.
    """
    if not isinstance(content, dict):
        raise ValueError(f"content bir dict değil: {type(content)}")

    # Title garantile
    if not content.get("title"):
        content["title"] = topic_key.replace("_", " ").title() or "Günlük İçerik"

    # full_narration garantile
    if not content.get("full_narration"):
        # segments'ten bir araya getir
        segs = content.get("segments", [])
        if segs and isinstance(segs, list):
            texts = []
            for s in segs:
                if isinstance(s, dict):
                    t = s.get("narration") or s.get("text") or ""
                    if t:
                        texts.append(str(t))
            if texts:
                content["full_narration"] = " ".join(texts)

    # SEGMENTS — en kritik alan
    segments = content.get("segments")
    if not segments or not isinstance(segments, list) or len(segments) == 0:
        log.warning(f"⚠ segments boş/eksik — full_narration'dan üretiliyor")
        content["segments"] = _create_segments_from_narration(
            content.get("full_narration", ""),
            content.get("title", "")
        )
    else:
        # Segmentlerin geçerli olduğundan emin ol
        valid_segments = []
        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            narration = (seg.get("narration") or seg.get("text") or "").strip()
            if not narration:
                continue
            valid_segments.append({
                "narration": narration,
                "text": seg.get("text", narration[:60]),
                "section": seg.get("section", f"bolum{i+1}"),
                "time": seg.get("time", f"{i*8}-{(i+1)*8}s"),
            })
        if not valid_segments:
            log.warning(f"⚠ Hiçbir segment geçerli değil — narration'dan yeniden üretiliyor")
            content["segments"] = _create_segments_from_narration(
                content.get("full_narration", "") or content.get("title", ""),
                content.get("title", "")
            )
        else:
            content["segments"] = valid_segments

    # Son kontrol — hala segment yoksa emergency fallback
    if not content.get("segments"):
        emergency_text = (content.get("title") or topic_key
                          or "Bugün için özel bir gündür.")
        content["segments"] = [{
            "narration": emergency_text,
            "text": emergency_text[:60],
            "section": "acil",
            "time": "0-30s",
        }]
        log.warning("⚠ EMERGENCY fallback — tek segment ile devam")

    # Diğer garantiler
    if "description" not in content:
        content["description"] = content.get("title", "")
    if "tags" not in content or not isinstance(content["tags"], list):
        content["tags"] = ["shorts", "günlük"]
    if "hashtags" not in content or not isinstance(content["hashtags"], list):
        content["hashtags"] = ["#Shorts"]

    log.info(f"✅ Content validate edildi — {len(content['segments'])} segment")
    return content


def _create_segments_from_narration(narration: str, title: str = "") -> list:
    """Verilen narration'ı 3-5 segmente böler."""
    if not narration:
        narration = title or "Bugün için özel bir mesajımız var."

    # Cümlelere böl
    sentences = re.split(r'(?<=[.!?])\s+', narration.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        # Kelimelere göre böl (son çare)
        words = narration.split()
        chunk_size = max(10, len(words) // 4)
        sentences = [
            " ".join(words[i:i + chunk_size])
            for i in range(0, len(words), chunk_size)
        ]

    if not sentences:
        return [{
            "narration": narration or title or "Devam ediyoruz.",
            "text": (narration or title or "Devam ediyoruz.")[:60],
            "section": "genel",
            "time": "0-30s",
        }]

    # Cümleleri 3-5 segmente grupla
    target_segments = min(5, max(3, len(sentences)))
    per_segment = max(1, len(sentences) // target_segments)

    segments = []
    for i in range(0, len(sentences), per_segment):
        chunk = " ".join(sentences[i:i + per_segment])
        if not chunk.strip():
            continue
        seg_idx = len(segments)
        segments.append({
            "narration": chunk,
            "text": chunk[:60] + ("..." if len(chunk) > 60 else ""),
            "section": f"bolum{seg_idx + 1}",
            "time": f"{seg_idx * 8}-{(seg_idx + 1) * 8}s",
        })
        if len(segments) >= 5:
            break

    # En az 1 segment garantisi
    if not segments:
        segments = [{
            "narration": narration,
            "text": narration[:60],
            "section": "genel",
            "time": "0-30s",
        }]

    return segments
