"""
Video Render Servisi
MoviePy ile 9:16 Shorts videosu üretir:
- Ken Burns zoom efekti
- Bölümlü altyazı (Aşk, Kariyer, Sağlık, Şanslı)
- Dinamik intro/outro
- TTS ses + arka plan müzik
"""

import os
import re
import random
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoClip, AudioFileClip, CompositeAudioClip,
    concatenate_audioclips, concatenate_videoclips
)

from services.images import fetch_image_urls, download_and_prepare, create_fallback_image
from services.tts import generate_tts

log = logging.getLogger(__name__)

# Video boyutları
W, H = 1080, 1920
FPS = 24

# Font aramak için olası yollar (Linux + Windows)
_FONT_CANDIDATES = [
    # Proje içi (varsa)
    "font/Montserrat-Bold.ttf",
    "font/Montserrat-ExtraBold.ttf",
    # Linux (Docker/Railway)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
    # Windows (yerel geliştirme)
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    r"C:\Windows\Fonts\seguiemj.ttf",
]


def _get_font(size: int):
    """İlk bulunan uygun fontu döner."""
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _ease_out(t: float) -> float:
    return 1 - (1 - min(1.0, max(0.0, t))) ** 3


def _ken_burns(img: Image.Image, t: float, duration: float,
               zoom_in: bool = True, direction: str = "center") -> np.ndarray:
    """Ken Burns (yumuşak zoom + pan) efekti."""
    p = min(1.0, t / max(duration, 0.01))
    zoom = 1.0 + 0.18 * p if zoom_in else 1.18 - 0.18 * p
    dirs = {
        "center": (0.5, 0.45),
        "left": (0.35 + 0.15 * p, 0.45),
        "right": (0.65 - 0.15 * p, 0.45),
        "up": (0.5, 0.35 + 0.15 * p),
        "down": (0.5, 0.55 - 0.10 * p),
    }
    cx, cy = dirs.get(direction, (0.5, 0.45))
    nw, nh = int(W * zoom), int(H * zoom)
    zoomed = img.resize((nw, nh), Image.LANCZOS)
    left = max(0, min(int(cx * nw - W / 2), nw - W))
    top = max(0, min(int(cy * nh - H / 2), nh - H))
    return np.array(zoomed.crop((left, top, left + W, top + H)))


def _wrap_text(draw, text: str, font, max_w: int) -> list:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textbbox((0, 0), test, font=font)[2] > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def _first_sentence(text: str, max_chars: int = 70) -> str:
    """Bir metinden altyazıya uygun kısa ifade çıkarır.
    Önce ilk cümleyi dener; çok uzunsa max_chars'e keser."""
    if not text:
        return ""
    text = text.strip()
    # İlk cümle sonu noktası bul
    for i, ch in enumerate(text):
        if ch in ".!?":
            first = text[:i + 1].strip()
            if len(first) <= max_chars:
                return first
            break
    # Cümle sonu bulunmadı veya ilk cümle çok uzun — kelime sınırında kes
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # Son boşluğa kadar kırp, ortada kelime kırılmasın
    last_space = cut.rfind(" ")
    if last_space > max_chars * 0.6:
        cut = cut[:last_space]
    return cut.rstrip(" ,;:") + "..."


def _add_text_overlay(frame_arr, t: float, text: str, seg_dur: float,
                      accent_hex: str, sign_name: str = "",
                      section_label: str = "", seg_idx: int = 0,
                      total: int = 1, show_header: bool = False) -> np.ndarray:
    """Video karesine metin overlay'i ekler."""
    img = Image.fromarray(frame_arr).convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    ac = _hex_to_rgb(accent_hex)

    fi = _ease_out(t / 0.5)
    fo = _ease_out((seg_dur - t) / 0.4) if t > seg_dur - 0.4 else 1.0
    alpha = min(fi, fo)

    # Alt gradient (metin okunurluğu için)
    for y in range(400):
        a = int(190 * _ease_out(1 - y / 400) * alpha)
        draw.line([(0, H - 400 + y), (W, H - 400 + y)], fill=(0, 0, 0, a))
    # Üst gradient
    for y in range(220):
        a = int(170 * _ease_out(1 - y / 220) * alpha)
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, a))

    # Alt accent çizgi
    bw = int(W * alpha)
    draw.rectangle([(W - bw) // 2, H - 6, (W + bw) // 2, H],
                   fill=(*ac, int(255 * alpha)))

    # İlerleme noktaları
    sp = 30
    tw = total * sp
    sx = (W - tw) // 2
    dy = H - 52
    for i in range(total):
        cx = sx + i * sp + sp // 2
        if i == seg_idx:
            draw.ellipse([cx - 8, dy - 8, cx + 8, dy + 8],
                         fill=(*ac, int(255 * alpha)))
        else:
            draw.ellipse([cx - 4, dy - 4, cx + 4, dy + 4],
                         fill=(180, 180, 180, int(80 * alpha)))

    # Bölüm etiketi (💕 Aşk, 💼 Kariyer vb)
    if section_label and section_label.strip():
        sf = _get_font(40)
        sb = draw.textbbox((0, 0), section_label, font=sf)
        sw = sb[2]
        sx2 = (W - sw) // 2
        sy2 = 260
        draw.rounded_rectangle(
            [sx2 - 28, sy2 - 12, sx2 + sw + 28, sy2 + 56],
            radius=30, fill=(0, 0, 0, int(180 * alpha)),
            outline=(*ac, int(220 * alpha)), width=3
        )
        draw.text((sx2, sy2), section_label, font=sf,
                  fill=(255, 245, 220, int(250 * alpha)))

    # Ana metin (ortalanmış)
    slide = int(25 * (1 - _ease_out(t / 0.4)))
    mfont = _get_font(54)
    lines = _wrap_text(draw, text, mfont, W - 100)
    lh = int(54 * 1.4)
    th = len(lines) * lh
    ty = (H // 2) - th // 2 + 100 + slide

    for line in lines:
        bb = draw.textbbox((0, 0), line, font=mfont)
        lw = bb[2]
        x = (W - lw) // 2
        for ox, oy in [(-4, -4), (4, -4), (-4, 4), (4, 4),
                       (0, -5), (0, 5), (-5, 0), (5, 0)]:
            draw.text((x + ox, ty + oy), line, font=mfont,
                      fill=(0, 0, 0, int(230 * alpha)))
        draw.text((x, ty), line, font=mfont,
                  fill=(255, 252, 240, int(255 * alpha)))
        ty += lh

    # İlk segmentte burç adı + tarih başlığı
    if show_header and sign_name:
        tf = _get_font(46)
        ty2 = 80
        tb = draw.textbbox((0, 0), sign_name, font=tf)
        tw2 = tb[2]
        tx = (W - tw2) // 2
        for ox, oy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]:
            draw.text((tx + ox, ty2 + oy), sign_name, font=tf,
                      fill=(0, 0, 0, int(220 * alpha)))
        draw.text((tx, ty2), sign_name, font=tf,
                  fill=(*ac, int(245 * alpha)))

        datestr = datetime.now().strftime("%d %B %Y")
        df = _get_font(28)
        db = draw.textbbox((0, 0), datestr, font=df)
        dw = db[2]
        dx = (W - dw) // 2
        dy_d = ty2 + 68
        draw.text((dx, dy_d), datestr, font=df,
                  fill=(220, 220, 220, int(200 * alpha)))

    result = Image.alpha_composite(img, overlay)
    return np.array(result.convert("RGB"))


def _add_lucky_bar(frame_arr, t: float, duration: float, accent_hex: str,
                   card: dict = None) -> np.ndarray:
    """Son segment için alt bilgi kartı. card dict yapısı:
    - type: 'triple' → 3 sütun (şanslı sayı/renk/uyumlu burç)
      {'type':'triple', 'col1':(label,val), 'col2':..., 'col3':...}
    - type: 'single' → tek mesaj (motivasyon key message)
      {'type':'single', 'label':'...', 'value':'...'}
    card None veya boşsa hiçbir şey çizmez.
    """
    if not card:
        return frame_arr

    img = Image.fromarray(frame_arr).convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    ac = _hex_to_rgb(accent_hex)

    fi = _ease_out(t / 0.6)
    fo = _ease_out((duration - t) / 0.4) if t > duration - 0.4 else 1.0
    alpha = min(fi, fo)

    card_type = card.get("type", "triple")

    if card_type == "triple":
        # Klasik 3 sütun (burç)
        cols = [
            card.get("col1", ("", "")),
            card.get("col2", ("", "")),
            card.get("col3", ("", "")),
        ]
        card_y = H - 560
        card_h = 260
        draw.rounded_rectangle(
            [60, card_y, W - 60, card_y + card_h],
            radius=24, fill=(0, 0, 0, int(200 * alpha)),
            outline=(*ac, int(200 * alpha)), width=3
        )
        col_w = (W - 120) // 3
        lf = _get_font(24)
        vf = _get_font(42)

        for i, (label, val) in enumerate(cols):
            cx = 60 + col_w * i + col_w // 2
            lb = draw.textbbox((0, 0), str(label), font=lf)
            draw.text((cx - lb[2] // 2, card_y + 40), str(label), font=lf,
                      fill=(200, 200, 200, int(230 * alpha)))
            vb = draw.textbbox((0, 0), str(val), font=vf)
            draw.text((cx - vb[2] // 2, card_y + 100), str(val), font=vf,
                      fill=(*ac, int(250 * alpha)))
            if i < 2:
                dx = 60 + col_w * (i + 1)
                draw.line([(dx, card_y + 40), (dx, card_y + card_h - 40)],
                          fill=(*ac, int(120 * alpha)), width=2)
    elif card_type == "single":
        # Tek büyük mesaj (motivasyon)
        label = str(card.get("label", ""))
        value = str(card.get("value", ""))
        card_y = H - 480
        card_h = 260
        draw.rounded_rectangle(
            [60, card_y, W - 60, card_y + card_h],
            radius=24, fill=(0, 0, 0, int(210 * alpha)),
            outline=(*ac, int(220 * alpha)), width=3
        )
        # Label üstte
        lf = _get_font(24)
        lb = draw.textbbox((0, 0), label, font=lf)
        lx = (W - lb[2]) // 2
        draw.text((lx, card_y + 30), label, font=lf,
                  fill=(*ac, int(230 * alpha)))
        # Value altta, wrap ile
        vf = _get_font(34)
        lines = _wrap_text(draw, value, vf, W - 180)[:3]
        lh = int(34 * 1.35)
        th = len(lines) * lh
        ty = card_y + 85 + max(0, (card_h - 85 - th) // 2)
        for line in lines:
            lb = draw.textbbox((0, 0), line, font=vf)
            lx = (W - lb[2]) // 2
            draw.text((lx, ty), line, font=vf,
                      fill=(255, 245, 220, int(250 * alpha)))
            ty += lh

    result = Image.alpha_composite(img, overlay)
    return np.array(result.convert("RGB"))


def _make_intro_clip(duration: float, sign_name: str, sign_symbol: str,
                     accent_hex: str, bg_hex: str,
                     subtitle: str = "Günlük Yorum",
                     face_image_path: str = None) -> VideoClip:
    """Dinamik intro klibi. face_image_path verilirse arka planda kullanılır
    (motivasyon kanalı için kadın yüzü konsepti)."""
    ac = _hex_to_rgb(accent_hex)
    try:
        bg = _hex_to_rgb(bg_hex)
    except Exception:
        bg = (10, 5, 20)

    # Eğer face image varsa onu arka plan olarak kullan
    if face_image_path and os.path.exists(face_image_path):
        try:
            face_img = Image.open(face_image_path).convert("RGB")
            # Resize to (W, H) — center crop
            iw, ih = face_img.size
            target_ratio = W / H
            if iw / ih > target_ratio:
                new_h = H
                new_w = int(iw * H / ih)
                face_img = face_img.resize((new_w, new_h), Image.LANCZOS)
                left = (new_w - W) // 2
                face_img = face_img.crop((left, 0, left + W, H))
            else:
                new_w = W
                new_h = int(ih * W / iw)
                face_img = face_img.resize((new_w, new_h), Image.LANCZOS)
                top = (new_h - H) // 2
                face_img = face_img.crop((0, top, W, top + H))
            face_img = face_img.resize((W, H), Image.LANCZOS)
            base_arr = np.array(face_img)
        except Exception as e:
            log.warning(f"Intro face image yüklenemedi: {e}, fallback gradient")
            face_image_path = None  # fallback'e düş

    if not (face_image_path and os.path.exists(face_image_path)):
        # Klasik gradient + halo
        base = Image.new("RGB", (W, H))
        draw = ImageDraw.Draw(base)
        c2 = tuple(min(255, c + 40) for c in bg)
        for y in range(H):
            t = y / H
            r = int(bg[0] * (1 - t) + c2[0] * t)
            g = int(bg[1] * (1 - t) + c2[1] * t)
            b = int(bg[2] * (1 - t) + c2[2] * t)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        cx, cy = W // 2, H // 2
        for radius in range(600, 0, -20):
            ratio = 1 - radius / 600
            ra = int(ac[0] * ratio * 0.25 + bg[0] * (1 - ratio * 0.3))
            ga = int(ac[1] * ratio * 0.25 + bg[1] * (1 - ratio * 0.3))
            ba = int(ac[2] * ratio * 0.25 + bg[2] * (1 - ratio * 0.3))
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                         fill=(ra, ga, ba))

        base_arr = np.array(base)

    def make_frame(t):
        frame = base_arr.copy()
        img = Image.fromarray(frame).convert("RGBA")
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)

        if t < 0.4:
            alpha = t / 0.4
        elif t > duration - 0.5:
            alpha = max(0.0, (duration - t) / 0.5)
        else:
            alpha = 1.0

        # Burç sembolü (büyük)
        sf = _get_font(360)
        sb = d.textbbox((0, 0), sign_symbol, font=sf)
        sw = sb[2] - sb[0]
        sh = sb[3] - sb[1]
        scale = 0.9 + 0.1 * _ease_out(min(1.0, t / 0.6))
        sx = (W - int(sw * scale)) // 2 - sb[0]
        sy = H // 2 - int(sh * scale) // 2 - sb[1] - 80
        for ox, oy in [(-6, -6), (6, -6), (-6, 6), (6, 6), (0, -8), (0, 8)]:
            d.text((sx + ox, sy + oy), sign_symbol, font=sf,
                   fill=(*ac, int(80 * alpha)))
        d.text((sx, sy), sign_symbol, font=sf,
               fill=(*ac, int(250 * alpha)))

        # Burç adı
        nf = _get_font(88)
        nb = d.textbbox((0, 0), sign_name, font=nf)
        nw = nb[2]
        nx = (W - nw) // 2
        ny = H // 2 + 280
        for ox, oy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]:
            d.text((nx + ox, ny + oy), sign_name, font=nf,
                   fill=(0, 0, 0, int(200 * alpha)))
        d.text((nx, ny), sign_name, font=nf,
               fill=(255, 245, 220, int(250 * alpha)))

        # Tarih
        datestr = datetime.now().strftime("%d %B %Y")
        df = _get_font(36)
        db = d.textbbox((0, 0), datestr, font=df)
        dw = db[2]
        dx = (W - dw) // 2
        dy = ny + 120
        d.text((dx, dy), datestr, font=df,
               fill=(220, 220, 220, int(230 * alpha)))

        # Alt başlık — kanal tipine göre dinamik
        sub = subtitle
        sbf = _get_font(30)
        sbb = d.textbbox((0, 0), sub.upper(), font=sbf)
        sbw = sbb[2]
        sbx = (W - sbw) // 2
        sby = dy + 70
        d.text((sbx, sby), sub.upper(), font=sbf,
               fill=(*ac, int(200 * alpha)))

        result = Image.alpha_composite(img, ov)
        return np.array(result.convert("RGB"))

    return VideoClip(make_frame, duration=duration)


def _make_outro_clip(duration: float, sign_name: str,
                     accent_hex: str, bg_hex: str,
                     subtitle: str = "Her gün yeni içerik") -> VideoClip:
    """Abone ol CTA'lı kısa outro. subtitle kanal tipine göre değişir."""
    ac = _hex_to_rgb(accent_hex)
    try:
        bg = _hex_to_rgb(bg_hex)
    except Exception:
        bg = (10, 5, 20)

    base = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(base)
    c2 = tuple(min(255, c + 30) for c in bg)
    for y in range(H):
        t = y / H
        r = int(bg[0] * (1 - t) + c2[0] * t)
        g = int(bg[1] * (1 - t) + c2[1] * t)
        b = int(bg[2] * (1 - t) + c2[2] * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    base_arr = np.array(base)

    def make_frame(t):
        img = Image.fromarray(base_arr.copy()).convert("RGBA")
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)

        if t < 0.4:
            alpha = t / 0.4
        elif t > duration - 0.5:
            alpha = max(0.0, (duration - t) / 0.5)
        else:
            alpha = 1.0

        main = "ABONE OL"
        mf = _get_font(110)
        mb = d.textbbox((0, 0), main, font=mf)
        mw = mb[2]
        mx = (W - mw) // 2
        my = H // 2 - 120
        for ox, oy in [(-5, -5), (5, -5), (-5, 5), (5, 5)]:
            d.text((mx + ox, my + oy), main, font=mf,
                   fill=(0, 0, 0, int(220 * alpha)))
        d.text((mx, my), main, font=mf,
               fill=(*ac, int(250 * alpha)))

        sub = subtitle
        sf = _get_font(44)
        sb = d.textbbox((0, 0), sub, font=sf)
        sw = sb[2]
        sx = (W - sw) // 2
        sy = my + 160
        d.text((sx, sy), sub, font=sf,
               fill=(255, 245, 220, int(240 * alpha)))

        nf = _get_font(36)
        nb = d.textbbox((0, 0), sign_name, font=nf)
        nw = nb[2]
        nx = (W - nw) // 2
        ny = sy + 110
        d.text((nx, ny), sign_name.upper(), font=nf,
               fill=(200, 200, 200, int(220 * alpha)))

        result = Image.alpha_composite(img, ov)
        return np.array(result.convert("RGB"))

    return VideoClip(make_frame, duration=duration)


def _find_bg_music(duration_needed: float) -> Optional[str]:
    """Arka plan müzik dosyasını bulur. `shortmusic/` klasörüne bakar."""
    music_dir = Path("shortmusic")
    if not music_dir.exists():
        return None
    candidates = list(music_dir.glob("*.mp3"))
    if not candidates:
        return None
    return str(random.choice(candidates))


def render_video(content: dict, output_path: str,
                 sign_key: Optional[str] = None,
                 voice_config: dict = None) -> str:
    """Content dict'ten video render eder ve kaydeder.

    voice_config: TTS için ses ayarları (kanaldan gelir).
    """
    # Job tracker + cancel opsiyonel
    jt = None
    cancel_mgr = None
    if sign_key:
        try:
            import job_tracker as jt
        except Exception:
            jt = None
        try:
            import cancel_manager as cancel_mgr
        except Exception:
            cancel_mgr = None

    def check_cancel():
        if cancel_mgr and sign_key:
            cancel_mgr.check_is_cancelled(sign_key)

    # Kanal tipine göre ana başlık ve sembol
    # Burç: sign_name, sign_symbol (♈♉♊...)
    # Motivasyon: topic_label, icon (🏆🎯🧘...)
    # Generic: content.main_label, content.main_icon
    sign_name = (content.get("main_label")
                 or content.get("sign_name")
                 or content.get("topic_label", ""))
    sign_symbol = (content.get("main_icon")
                   or content.get("sign_symbol", "")
                   or content.get("topic_icon", ""))
    # Intro alt yazısı — kanal tipine göre
    intro_subtitle = content.get("intro_subtitle", "Günlük Yorum")

    segments = content.get("segments", [])[:6]
    accent = content.get("accent_color", "#7c3aed")
    bg = content.get("background_color", "#15081f")
    queries = content.get("pexels_queries", [])

    # Lucky card — kanal modülünden gelen lucky_card yapısına göre
    # (type: "triple" = burç 3 sütun, type: "single" = motivasyon tek mesaj)
    lucky_card = content.get("lucky_card")

    # Geriye uyumluluk — eski zodiac yapısı
    lucky_num = content.get("lucky_number", "")
    lucky_col = content.get("lucky_color", "")
    compat = content.get("compatible_sign", "")

    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"🎬 Video render başlıyor: {sign_name}")

    # 1) Görselleri indir
    if jt and sign_key:
        jt.update_stage(sign_key, jt.STAGE_IMAGES,
                        detail=f"{len(queries)} sorgu aranıyor")
    log.info(f"🔍 Görseller aranıyor...")
    urls = fetch_image_urls(queries, count=len(segments) + 2)
    random.shuffle(urls)

    images = []
    for url in urls:
        if len(images) >= len(segments):
            break
        img = download_and_prepare(url, W, H, accent)
        if img:
            images.append(img)
            if jt and sign_key:
                jt.update_stage(sign_key, jt.STAGE_IMAGES,
                                detail=f"Görsel {len(images)}/{len(segments)}")

    idx = 0
    while len(images) < len(segments):
        images.append(create_fallback_image(W, H, accent, bg, idx))
        idx += 1
    log.info(f"✅ {len(images)} görsel hazır")

    # 2) TTS
    if jt and sign_key:
        jt.update_stage(sign_key, jt.STAGE_TTS, detail="Giriş sesi")
    log.info(f"🎙 Seslendirme...")
    seg_tts_paths = []
    seg_audio_clips = []
    seg_durations = []
    tmp_prefix = output_path.replace(".mp4", "")

    # Intro text — kanal tipine göre farklı (content'ten geliyor)
    intro_text = content.get("intro_text") or f"{sign_name} günlük yorum"
    intro_tts_path = f"{tmp_prefix}_intro_tts.mp3"
    check_cancel()
    generate_tts(intro_text, intro_tts_path, voice_config=voice_config)
    if cancel_mgr and sign_key:
        cancel_mgr.record_tts(sign_key, len(intro_text))
    intro_audio = AudioFileClip(intro_tts_path)
    intro_dur = max(intro_audio.duration + 0.8, 3.0)

    for i, seg in enumerate(segments):
        check_cancel()
        if jt and sign_key:
            jt.update_stage(sign_key, jt.STAGE_TTS,
                            detail=f"Segment {i + 1}/{len(segments)}")
        text = seg.get("narration") or seg.get("text", "") or content.get("full_narration", sign_name)
        tts_p = f"{tmp_prefix}_seg{i}_tts.mp3"
        generate_tts(text, tts_p, voice_config=voice_config)
        if cancel_mgr and sign_key:
            cancel_mgr.record_tts(sign_key, len(text))
        seg_tts_paths.append(tts_p)
        aclip = AudioFileClip(tts_p)
        sd = max(3.0, aclip.duration + 0.6)
        seg_audio_clips.append(aclip)
        seg_durations.append(sd)
        log.info(f"    Seg {i + 1} ({seg.get('section', '?')}): {sd:.1f}s")

    total_dur = sum(seg_durations)
    log.info(f"⏱ Toplam içerik: {total_dur:.1f}s")

    # 3) Video klipleri (RENDER aşaması başlıyor)
    if jt and sign_key:
        jt.update_stage(sign_key, jt.STAGE_RENDER,
                        detail="Video kareleri hazırlanıyor")

    dirs = ["center", "left", "right", "up", "down", "center"]
    clips = []

    for i, seg in enumerate(segments):
        img_arr = np.array(images[i])
        zoom_in = (i % 2 == 0)
        direction = dirs[i % len(dirs)]
        show_hdr = (i == 0)
        sd = seg_durations[i]
        narration_text = seg.get("narration") or seg.get("text", "")
        section_label = seg.get("text", "")
        if seg.get("section") in ("giris", "genel"):
            section_label = ""
        is_last = (i == len(segments) - 1)

        def make_frame(t, _img=img_arr, _txt=narration_text, _sd=sd,
                       _zi=zoom_in, _dir=direction, _i=i, _sh=show_hdr,
                       _sec=section_label, _last=is_last,
                       _card=lucky_card, _ln=lucky_num,
                       _lc=lucky_col, _cp=compat):
            frame = _ken_burns(Image.fromarray(_img), t, _sd, _zi, _dir)
            frame = _add_text_overlay(
                frame, t, _txt, _sd, accent,
                sign_name=sign_name if _sh else "",
                section_label=_sec,
                seg_idx=_i, total=len(segments),
                show_header=_sh,
            )
            if _last:
                card = _card
                if not card and (_ln or _lc or _cp):
                    card = {
                        "type": "triple",
                        "col1": ("ŞANSLI SAYI", _ln),
                        "col2": ("ŞANSLI RENK", _lc),
                        "col3": ("UYUMLU BURÇ", _cp),
                    }
                if card:
                    frame = _add_lucky_bar(frame, t, _sd, accent, card=card)
            return frame

        aclip = seg_audio_clips[i]
        fade_dur = min(0.5, aclip.duration * 0.15)
        aclip_faded = aclip.audio_fadeout(fade_dur).audio_fadein(0.1)
        seg_audio = aclip_faded.set_start(0.2)
        vc = VideoClip(make_frame, duration=sd).set_audio(seg_audio)
        clips.append(vc)

    # 4) Intro/outro
    intro_face = content.get("intro_face_image", "")
    intro_clip = _make_intro_clip(intro_dur, sign_name, sign_symbol,
                                  accent, bg, subtitle=intro_subtitle,
                                  face_image_path=intro_face)
    # Outro subtitle — kanal modülünden gelir, yoksa default
    outro_sub = content.get("outro_subtitle", "Her gün yeni içerik")
    outro_clip = _make_outro_clip(2.8, sign_name, accent, bg,
                                  subtitle=outro_sub)

    intro_audio_end = min(intro_dur, intro_audio.duration + 0.3)
    intro_audio_faded = intro_audio.audio_fadeout(0.3)
    intro_clip = intro_clip.set_audio(
        intro_audio_faded.set_start(0.3).set_end(intro_audio_end)
    )

    # 5) Birleştir
    content_clip = concatenate_videoclips(clips, method="chain")
    final = concatenate_videoclips([intro_clip, content_clip, outro_clip],
                                   method="chain")
    full_dur = intro_dur + total_dur + 2.8

    # 6) Arka plan müziği (varsa)
    music_path = _find_bg_music(full_dur)
    if music_path and os.path.exists(music_path):
        try:
            music = AudioFileClip(music_path)
            if music.duration < full_dur:
                loops = int(np.ceil(full_dur / music.duration)) + 1
                music = concatenate_audioclips([music] * loops)
            music = music.subclip(0, full_dur).volumex(0.07)
            existing_audio = final.audio
            if existing_audio:
                audio = CompositeAudioClip([existing_audio, music]).set_end(full_dur)
            else:
                audio = music
            final = final.set_audio(audio)
            log.info(f"🎵 Müzik: {os.path.basename(music_path)}")
        except Exception as e:
            log.warning(f"Müzik eklenemedi: {e}")

    # 7) Kaydet
    if jt and sign_key:
        jt.update_stage(sign_key, jt.STAGE_RENDER,
                        detail=f"Video dosyası kaydediliyor (~{int(full_dur)}s)")
    log.info(f"💾 Kaydediliyor...")
    final.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        logger=None,
        threads=4,
        preset="ultrafast",
        ffmpeg_params=["-crf", "26", "-movflags", "+faststart"],
    )

    # 8) Temp ses dosyalarını temizle
    for f in [intro_tts_path] + seg_tts_paths:
        try:
            os.remove(f)
        except Exception:
            pass

    mb = os.path.getsize(output_path) / (1024 * 1024)
    log.info(f"✅ Video hazır: {output_path} ({mb:.1f} MB)")
    return output_path
