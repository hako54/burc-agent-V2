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
from functools import lru_cache
from pathlib import Path
from datetime import datetime

from services.tr_locale import tr_date, tr_upper
from typing import List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:  # OpenCV varsa Ken Burns ~6 kat hızlı; yoksa Pillow'a düşer
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None
from moviepy.editor import (
    VideoClip, VideoFileClip, AudioFileClip, CompositeAudioClip,
    concatenate_audioclips, concatenate_videoclips
)

from services.emoji_text import (draw_text, text_width, is_emoji_only,
                                 emoji_image, paste_image)
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


@lru_cache(maxsize=64)
def _get_font(size: int):
    """İlk bulunan uygun fontu döner. Önbellekli: her karede diskten
    yeniden okumak render'ı ciddi yavaşlatıyordu."""
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
    left = max(0, min(int(cx * nw - W / 2), nw - W))
    top = max(0, min(int(cy * nh - H / 2), nh - H))
    # Tüm görseli büyütüp kırpmak yerine kaynaktaki ilgili bölgeyi tek
    # adımda W×H'ye büyüt (aynı kadraj, çok daha hızlı)
    if isinstance(img, np.ndarray):
        ih, iw = img.shape[:2]
    else:
        iw, ih = img.size
    kx, ky = nw / iw, nh / ih
    if cv2 is not None:
        arr = img if isinstance(img, np.ndarray) else np.asarray(img)
        m = np.float32([[kx, 0, -left], [0, ky, -top]])
        return cv2.warpAffine(arr, m, (W, H), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img)
    box = (left / kx, top / ky, (left + W) / kx, (top + H) / ky)
    return np.array(img.resize((W, H), Image.BILINEAR, box=box))


def _wrap_text(draw, text: str, font, max_w: int) -> list:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if text_width(draw, test, font) > max_w and cur:
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


def _scaled_alpha(layer: Image.Image, alpha: float) -> Image.Image:
    """RGBA katmanın saydamlığını alpha (0-1) ile çarpar."""
    if alpha >= 0.999:
        return layer
    out = layer.copy()
    out.putalpha(layer.getchannel("A").point(lambda a: int(a * alpha)))
    return out


@lru_cache(maxsize=8)
def _text_layers(text: str, accent_hex: str, sign_name: str,
                 section_label: str, seg_idx: int, total: int,
                 show_header: bool):
    """Bir segmentin yazı katmanlarını tam görünürlükte (alpha=1) bir kez
    çizer. Dönüş: (sabit katman, (ana metin katmanı, x, y)).
    Her karede yeniden çizmek yerine bunlar saydamlığı ayarlanarak
    kullanılır."""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    ac = _hex_to_rgb(accent_hex)

    # Alt gradient (metin okunurluğu için)
    for y in range(400):
        a = int(190 * _ease_out(1 - y / 400))
        draw.line([(0, H - 400 + y), (W, H - 400 + y)], fill=(0, 0, 0, a))
    # Üst gradient
    for y in range(220):
        a = int(170 * _ease_out(1 - y / 220))
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, a))

    # İlerleme noktaları
    sp = 30
    tw = total * sp
    sx = (W - tw) // 2
    dy = H - 52
    for i in range(total):
        cx = sx + i * sp + sp // 2
        if i == seg_idx:
            draw.ellipse([cx - 8, dy - 8, cx + 8, dy + 8], fill=(*ac, 255))
        else:
            draw.ellipse([cx - 4, dy - 4, cx + 4, dy + 4],
                         fill=(180, 180, 180, 80))

    # Bölüm etiketi (💕 Aşk, 💼 Kariyer vb)
    if section_label and section_label.strip():
        sf = _get_font(40)
        sw = text_width(draw, section_label, sf)
        sx2 = (W - sw) // 2
        sy2 = 260
        draw.rounded_rectangle(
            [sx2 - 28, sy2 - 12, sx2 + sw + 28, sy2 + 56],
            radius=30, fill=(0, 0, 0, 180),
            outline=(*ac, 220), width=3
        )
        draw_text(overlay, draw, (sx2, sy2), section_label, sf,
                  (255, 245, 220, 250))

    # İlk segmentte burç adı + tarih başlığı
    if show_header and sign_name:
        # Otomatik boyut — uzun başlık için küçült
        max_header_w = W - 200
        tf_size = 46
        tf = _get_font(tf_size)
        tw2 = text_width(draw, sign_name, tf)
        while tw2 > max_header_w and tf_size > 30:
            tf_size -= 4
            tf = _get_font(tf_size)
            tw2 = text_width(draw, sign_name, tf)
        # Hala sığmıyorsa wrap et
        if tw2 > max_header_w:
            header_lines = _wrap_text(draw, sign_name, tf, max_header_w)
        else:
            header_lines = [sign_name]

        ty2 = 80
        line_h2 = int(tf_size * 1.15)
        for line in header_lines:
            lw = text_width(draw, line, tf)
            tx = (W - lw) // 2
            for ox, oy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]:
                draw_text(overlay, draw, (tx + ox, ty2 + oy), line, tf,
                          (0, 0, 0, 220), emoji=False)
            draw_text(overlay, draw, (tx, ty2), line, tf, (*ac, 245))
            ty2 += line_h2

        datestr = tr_date()
        df = _get_font(28)
        db = draw.textbbox((0, 0), datestr, font=df)
        dw = db[2]
        dx = (W - dw) // 2
        dy_d = ty2 + 22
        draw.text((dx, dy_d), datestr, font=df, fill=(220, 220, 220, 200))

    # Ana metin (ortalanmış) — ayrı katman, çünkü girişte kayarak geliyor
    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(text_layer)

    # Otomatik boyut ayarı — uzun metinleri sığdırmak için
    # Kenarlardan 110px boşluk (her iki yan)
    max_w = W - 220   # 1080 - 220 = 860px güvenli alan
    font_size = 54
    mfont = _get_font(font_size)
    lines = _wrap_text(tdraw, text, mfont, max_w)

    # Çok uzunsa font'u küçült
    while len(lines) > 4 and font_size > 38:
        font_size -= 4
        mfont = _get_font(font_size)
        lines = _wrap_text(tdraw, text, mfont, max_w)

    # Hala 5+ satırsa son çare: 36'ya kadar küçült
    while len(lines) > 5 and font_size > 32:
        font_size -= 2
        mfont = _get_font(font_size)
        lines = _wrap_text(tdraw, text, mfont, max_w)

    lh = int(font_size * 1.35)
    th = len(lines) * lh
    ty = (H // 2) - th // 2 + 100

    # Outline kalınlığını font boyutuna göre ayarla
    outline_offsets = [(-4, -4), (4, -4), (-4, 4), (4, 4),
                       (0, -5), (0, 5), (-5, 0), (5, 0)]
    if font_size <= 42:
        outline_offsets = [(-3, -3), (3, -3), (-3, 3), (3, 3),
                           (0, -3), (0, 3), (-3, 0), (3, 0)]

    for line in lines:
        lw = text_width(tdraw, line, mfont)
        x = (W - lw) // 2
        for ox, oy in outline_offsets:
            draw_text(text_layer, tdraw, (x + ox, ty + oy), line, mfont,
                      (0, 0, 0, 230), emoji=False)
        draw_text(text_layer, tdraw, (x, ty), line, mfont,
                  (255, 252, 240, 255))
        ty += lh

    # Sadece metnin kapladığı bölgeyi sakla (kaydırma ucuz olsun)
    bbox = text_layer.getbbox()
    if bbox:
        text_part = (text_layer.crop(bbox), bbox[0], bbox[1])
    else:
        text_part = None
    return overlay, text_part


def _add_text_overlay(frame_arr, t: float, text: str, seg_dur: float,
                      accent_hex: str, sign_name: str = "",
                      section_label: str = "", seg_idx: int = 0,
                      total: int = 1, show_header: bool = False) -> np.ndarray:
    """Video karesine metin overlay'i ekler (numpy giriş/çıkış)."""
    img = Image.fromarray(frame_arr).convert("RGBA")
    _apply_text_overlay(img, t, text, seg_dur, accent_hex, sign_name,
                        section_label, seg_idx, total, show_header)
    return np.array(img.convert("RGB"))


def _apply_text_overlay(img: Image.Image, t: float, text: str,
                        seg_dur: float, accent_hex: str, sign_name: str = "",
                        section_label: str = "", seg_idx: int = 0,
                        total: int = 1, show_header: bool = False):
    """RGBA kareye yazı katmanlarını yerinde uygular. Katmanlar segment
    başına bir kez çizilir (_text_layers); burada sadece saydamlık ve
    kayma uygulanır."""
    ac = _hex_to_rgb(accent_hex)

    fi = _ease_out(t / 0.5)
    fo = _ease_out((seg_dur - t) / 0.4) if t > seg_dur - 0.4 else 1.0
    alpha = min(fi, fo)
    if alpha <= 0:
        return

    static_layer, text_part = _text_layers(
        text, accent_hex, sign_name, section_label, seg_idx, total,
        show_header)
    img.alpha_composite(_scaled_alpha(static_layer, alpha))

    # Alt accent çizgi — genişliği alpha ile büyür
    bw = int(W * alpha)
    if bw > 0:
        bar = Image.new("RGBA", (min(bw + 1, W), 6),
                        (*ac, int(255 * alpha)))
        img.alpha_composite(bar, dest=((W - bw) // 2, H - 6))

    # Ana metin — girişte 25px aşağıdan kayarak gelir
    if text_part:
        layer, x, y = text_part
        slide = int(25 * (1 - _ease_out(t / 0.4)))
        dest_y = y + slide
        if dest_y + layer.height > H:
            layer = layer.crop((0, 0, layer.width, H - dest_y))
        img.alpha_composite(_scaled_alpha(layer, alpha), dest=(x, dest_y))


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
    _apply_lucky_bar(img, t, duration, accent_hex, card)
    return np.array(img.convert("RGB"))


def _apply_lucky_bar(img: Image.Image, t: float, duration: float,
                     accent_hex: str, card: dict):
    """RGBA kareye şanslı kart katmanını yerinde uygular."""
    if not card:
        return
    fi = _ease_out(t / 0.6)
    fo = _ease_out((duration - t) / 0.4) if t > duration - 0.4 else 1.0
    alpha = min(fi, fo)
    if alpha <= 0:
        return

    key = (repr(sorted(card.items())), accent_hex)
    part = _LUCKY_CACHE.get(key)
    if part is None:
        if len(_LUCKY_CACHE) > 8:
            _LUCKY_CACHE.clear()
        part = _LUCKY_CACHE[key] = _draw_lucky_layer(card, accent_hex)
    if part is None:
        return

    layer, x, y = part
    img.alpha_composite(_scaled_alpha(layer, alpha), dest=(x, y))


# Şanslı kart katmanı önbelleği: (kart, renk) → (katman, x, y)
_LUCKY_CACHE: dict = {}


def _draw_lucky_layer(card: dict, accent_hex: str):
    """Kartı tam görünürlükte bir kez çizer; kırpılmış katman döner."""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    ac = _hex_to_rgb(accent_hex)

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
            radius=24, fill=(0, 0, 0, 200),
            outline=(*ac, 200), width=3
        )
        col_w = (W - 120) // 3
        lf = _get_font(24)
        vf = _get_font(42)

        for i, (label, val) in enumerate(cols):
            cx = 60 + col_w * i + col_w // 2
            lb = draw.textbbox((0, 0), str(label), font=lf)
            draw.text((cx - lb[2] // 2, card_y + 40), str(label), font=lf,
                      fill=(200, 200, 200, 230))
            vb = draw.textbbox((0, 0), str(val), font=vf)
            draw.text((cx - vb[2] // 2, card_y + 100), str(val), font=vf,
                      fill=(*ac, 250))
            if i < 2:
                dx = 60 + col_w * (i + 1)
                draw.line([(dx, card_y + 40), (dx, card_y + card_h - 40)],
                          fill=(*ac, 120), width=2)
    elif card_type == "single":
        # Tek büyük mesaj (motivasyon)
        label = str(card.get("label", ""))
        value = str(card.get("value", ""))
        card_y = H - 480
        card_h = 260
        draw.rounded_rectangle(
            [60, card_y, W - 60, card_y + card_h],
            radius=24, fill=(0, 0, 0, 210),
            outline=(*ac, 220), width=3
        )
        # Label üstte
        lf = _get_font(24)
        lb = draw.textbbox((0, 0), label, font=lf)
        lx = (W - lb[2]) // 2
        draw.text((lx, card_y + 30), label, font=lf,
                  fill=(*ac, 230))
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
                      fill=(255, 245, 220, 250))
            ty += lh

    bbox = overlay.getbbox()
    if not bbox:
        return None
    return overlay.crop(bbox), bbox[0], bbox[1]


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

    # Arka plan görseli (Söz/motivasyon dikey kapağı) zaten büyük başlık
    # içeriyor; ortaya ayrıca sembol çizmek o başlığı kapatıyordu.
    has_face_bg = bool(face_image_path and os.path.exists(face_image_path))
    draw_symbol = bool(sign_symbol) and not has_face_bg

    if not has_face_bg:
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
        scale = 0.9 + 0.1 * _ease_out(min(1.0, t / 0.6))
        if draw_symbol and is_emoji_only(sign_symbol, sf):
            # Renkli emoji (örn. motivasyon kategorisi 🏆) — fontta yok
            em = emoji_image(sign_symbol, int(300 * scale))
            if em is not None:
                paste_image(ov, em, ((W - em.width) // 2,
                                     H // 2 - em.height // 2 - 80),
                            alpha=alpha)
        elif draw_symbol:
            sb = d.textbbox((0, 0), sign_symbol, font=sf)
            sw = sb[2] - sb[0]
            sh = sb[3] - sb[1]
            sx = (W - int(sw * scale)) // 2 - sb[0]
            sy = H // 2 - int(sh * scale) // 2 - sb[1] - 80
            for ox, oy in [(-6, -6), (6, -6), (-6, 6), (6, 6),
                           (0, -8), (0, 8)]:
                d.text((sx + ox, sy + oy), sign_symbol, font=sf,
                       fill=(*ac, int(80 * alpha)))
            d.text((sx, sy), sign_symbol, font=sf,
                   fill=(*ac, int(250 * alpha)))

        # Burç adı / kategori adı / başlık — otomatik boyut ayarı
        # Mobilde sığması için max genişliği kontrol et, sığmazsa küçült
        max_text_w = W - 200  # her iki yanda 100px güvenli boşluk
        nf_size = 88
        nf = _get_font(nf_size)
        nw = text_width(d, sign_name, nf)
        # Sığmıyorsa font'u küçült
        while nw > max_text_w and nf_size > 40:
            nf_size -= 6
            nf = _get_font(nf_size)
            nw = text_width(d, sign_name, nf)
        # Hala sığmıyorsa wrap et (çok uzun başlık için)
        if nw > max_text_w:
            lines = _wrap_text(d, sign_name, nf, max_text_w)
        else:
            lines = [sign_name]

        # Çizim — birden fazla satır olabilir
        ny = H // 2 + 280
        line_h = int(nf_size * 1.1)
        # Birden fazla satır varsa biraz yukarı al
        if len(lines) > 1:
            ny -= (len(lines) - 1) * line_h // 2
        for line in lines:
            lw = text_width(d, line, nf)
            lx = (W - lw) // 2
            for ox, oy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]:
                draw_text(ov, d, (lx + ox, ny + oy), line, nf,
                          (0, 0, 0, int(200 * alpha)), emoji=False)
            draw_text(ov, d, (lx, ny), line, nf,
                      (255, 245, 220, int(250 * alpha)))
            ny += line_h
        # Tarih için ny'yi en son satırın altına ayarla
        ny = ny - line_h + nf_size + 40

        # Tarih
        datestr = tr_date()
        df = _get_font(36)
        db = d.textbbox((0, 0), datestr, font=df)
        dw = db[2]
        dx = (W - dw) // 2
        dy = ny + 80
        d.text((dx, dy), datestr, font=df,
               fill=(220, 220, 220, int(230 * alpha)))

        # Alt başlık — kanal tipine göre dinamik
        sub = subtitle
        sbf = _get_font(30)
        sbb = d.textbbox((0, 0), tr_upper(sub), font=sbf)
        sbw = sbb[2]
        sbx = (W - sbw) // 2
        sby = dy + 70
        d.text((sbx, sby), tr_upper(sub), font=sbf,
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
        name_up = tr_upper(sign_name)
        nw = text_width(d, name_up, nf)
        nx = (W - nw) // 2
        ny = sy + 110
        draw_text(ov, d, (nx, ny), name_up, nf,
                  (200, 200, 200, int(220 * alpha)))

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


# ── AI sunucu (HeyGen) klipleri ──────────────────────────────────────

def _fit_cover(frame: np.ndarray) -> np.ndarray:
    """Kareyi W×H'yi tamamen kaplayacak şekilde ölçekleyip ortadan kırpar."""
    h, w = frame.shape[:2]
    if (w, h) == (W, H):
        return frame
    s = max(W / w, H / h)
    nw, nh = max(W, round(w * s)), max(H, round(h * s))
    if cv2 is not None:
        interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
        fr = cv2.resize(frame, (nw, nh), interpolation=interp)
    else:
        fr = np.asarray(Image.fromarray(frame).resize((nw, nh), Image.LANCZOS))
    x, y = (nw - W) // 2, (nh - H) // 2
    return fr[y:y + H, x:x + W]


def _content_box(frame: np.ndarray, tol: float = 6.0):
    """HeyGen dikey olmayan fotoğrafı düz renkli boşlukla (letterbox)
    doldurur. Tek renkli kenar satır/sütunlarını atıp asıl görüntünün
    kutusunu döner; bulunamazsa None."""
    f = frame.astype(np.float32)
    rows = np.where(f.std(axis=(1, 2)) > tol)[0]
    cols = np.where(f.std(axis=(0, 2)) > tol)[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    x0, x1 = int(cols[0]), int(cols[-1]) + 1
    h, w = frame.shape[:2]
    if (y1 - y0) < h * 0.3 or (x1 - x0) < w * 0.3:
        return None
    if (y0, y1, x0, x1) == (0, h, 0, w):
        return None
    # Kenardaki sıkıştırma geçişini de at
    m = 4
    return (min(x0 + m, x1), min(y0 + m, y1),
            max(x1 - m, x0), max(y1 - m, y0))


def _presenter_label_layer(title: str, subtitle: str, accent_hex: str,
                           top: bool) -> np.ndarray:
    """Sunucu videosunun üstüne konan etiket (burç adı / abone çağrısı).
    float32 (H, W, 4) döner; alfa 0..1."""
    ac = _hex_to_rgb(accent_hex)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    tf, sf = _get_font(66), _get_font(38)
    tw = text_width(draw, title, tf)
    sw = text_width(draw, subtitle, sf) if subtitle else 0
    box_w = min(W - 80, max(tw, sw) + 100)
    box_h = 130 + (56 if subtitle else 0)
    x0 = (W - box_w) // 2
    y0 = 150 if top else H - box_h - 260
    draw.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=36,
                           fill=(10, 6, 20, 175), outline=ac + (255,),
                           width=4)
    draw_text(layer, draw, ((W - tw) // 2, y0 + 30), title, tf,
              (255, 255, 255, 255))
    if subtitle:
        draw_text(layer, draw, ((W - sw) // 2, y0 + 112), subtitle, sf,
                  ac + (255,))
    arr = np.asarray(layer).astype(np.float32)
    arr[..., 3] /= 255.0
    return arr


def _make_presenter_clip(video_path: str, title: str, subtitle: str,
                         accent_hex: str, top: bool) -> VideoClip:
    """HeyGen videosunu W×H'ye oturtur, etiketi ekler (sesi korunur)."""
    src = VideoFileClip(video_path)
    layer = _presenter_label_layer(title, subtitle, accent_hex, top)
    rgb, alpha = layer[..., :3], layer[..., 3:4]
    last_t = max(0.0, src.duration - 0.05)
    box = _content_box(src.get_frame(min(src.duration / 2, last_t)))
    if box:
        log.info(f"🎭 Sunucu videosundaki boşluk kırpılıyor: {box}")

    def make_frame(t):
        fr = src.get_frame(min(t, last_t))
        if box:
            x0, y0, x1, y1 = box
            fr = fr[y0:y1, x0:x1]
        fr = _fit_cover(np.ascontiguousarray(fr)).astype(np.float32)
        k = alpha * _ease_out(t / 0.5)
        return (fr * (1 - k) + rgb * k).astype(np.uint8)

    clip = VideoClip(make_frame, duration=src.duration)
    if src.audio is not None:
        clip = clip.set_audio(src.audio)
    return clip


def _start_presenter(content: dict, tmp_prefix: str, intro_tts_path: str,
                     voice_config: dict = None) -> dict:
    """Açılış/kapanış sunucu videolarını HeyGen'de başlatır. Hata olursa
    o parça atlanır (video eski açılış/kapanışla devam eder)."""
    from services import presenter
    jobs = {}
    title = content.get("sign_name") or content.get("title", "burc")
    try:
        jobs["intro"] = presenter.start_clip(intro_tts_path,
                                             f"{title} açılış")
    except Exception as e:
        log.warning(f"🎭 Sunucu açılışı başlatılamadı: {e}")
    outro_text = content.get("presenter_outro_text")
    if outro_text:
        outro_tts = f"{tmp_prefix}_outro_tts.mp3"
        try:
            generate_tts(outro_text, outro_tts, voice_config=voice_config)
            jobs["outro_tts"] = outro_tts
            jobs["outro"] = presenter.start_clip(outro_tts,
                                                 f"{title} kapanış")
        except Exception as e:
            log.warning(f"🎭 Sunucu kapanışı başlatılamadı: {e}")
    return jobs


def _fetch_presenter(jobs: dict, tmp_prefix: str, key: str, title: str,
                     subtitle: str, accent_hex: str, top: bool):
    """Başlatılan sunucu videosunu bekler/indirir; hata olursa None."""
    if not jobs.get(key):
        return None
    from services import presenter
    path = f"{tmp_prefix}_presenter_{key}.mp4"
    try:
        presenter.fetch_clip(jobs[key], path)
        jobs.setdefault("files", []).append(path)
        clip = _make_presenter_clip(path, title, subtitle, accent_hex, top)
        log.info(f"🎭 Sunucu {key} hazır ({clip.duration:.1f}s)")
        return clip
    except Exception as e:
        log.warning(f"🎭 Sunucu {key} kullanılamadı, klasik sürüm: {e}")
        return None


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

    # AI sunucu: HeyGen üretimi birkaç dakika sürer; şimdi başlatıp
    # segment seslendirmesi sürerken arka planda hazırlanmasını sağla
    presenter_jobs = {}
    if content.get("presenter"):
        presenter_jobs = _start_presenter(content, tmp_prefix,
                                          intro_tts_path, voice_config)

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
        img_src = np.asarray(images[i].convert("RGB"))
        zoom_in = (i % 2 == 0)
        direction = dirs[i % len(dirs)]
        show_hdr = (i == 0)
        sd = seg_durations[i]
        narration_text = seg.get("narration") or seg.get("text", "")
        section_label = seg.get("text", "")
        if seg.get("section") in ("giris", "genel"):
            section_label = ""
        is_last = (i == len(segments) - 1)

        def make_frame(t, _img=img_src, _txt=narration_text, _sd=sd,
                       _zi=zoom_in, _dir=direction, _i=i, _sh=show_hdr,
                       _sec=section_label, _last=is_last,
                       _card=lucky_card, _ln=lucky_num,
                       _lc=lucky_col, _cp=compat):
            img = Image.fromarray(
                _ken_burns(_img, t, _sd, _zi, _dir)).convert("RGBA")
            _apply_text_overlay(
                img, t, _txt, _sd, accent,
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
                    _apply_lucky_bar(img, t, _sd, accent, card)
            return np.array(img.convert("RGB"))

        aclip = seg_audio_clips[i]
        fade_dur = min(0.5, aclip.duration * 0.15)
        aclip_faded = aclip.audio_fadeout(fade_dur).audio_fadein(0.1)
        seg_audio = aclip_faded.set_start(0.2)
        vc = VideoClip(make_frame, duration=sd).set_audio(seg_audio)
        clips.append(vc)

    # 4) Intro/outro
    outro_sub = content.get("outro_subtitle", "Her gün yeni içerik")
    p_intro = p_outro = None
    if presenter_jobs:
        if jt and sign_key:
            jt.update_stage(sign_key, jt.STAGE_RENDER,
                            detail="AI sunucu videosu bekleniyor")
        label = f"{sign_symbol} {tr_upper(sign_name)}".strip()
        p_intro = _fetch_presenter(presenter_jobs, tmp_prefix, "intro",
                                   label, tr_date(), accent, top=True)
        p_outro = _fetch_presenter(presenter_jobs, tmp_prefix, "outro",
                                   "Abone ol 🔔", outro_sub, accent,
                                   top=False)

    if p_intro is not None:
        intro_clip = p_intro
        intro_dur = p_intro.duration
    else:
        intro_face = content.get("intro_face_image", "")
        intro_clip = _make_intro_clip(intro_dur, sign_name, sign_symbol,
                                      accent, bg, subtitle=intro_subtitle,
                                      face_image_path=intro_face)
        intro_audio_end = min(intro_dur, intro_audio.duration + 0.3)
        intro_audio_faded = intro_audio.audio_fadeout(0.3)
        intro_clip = intro_clip.set_audio(
            intro_audio_faded.set_start(0.3).set_end(intro_audio_end)
        )

    if p_outro is not None:
        outro_clip = p_outro
        outro_dur = p_outro.duration
    else:
        outro_dur = 2.8
        outro_clip = _make_outro_clip(outro_dur, sign_name, accent, bg,
                                      subtitle=outro_sub)

    # 5) Birleştir
    content_clip = concatenate_videoclips(clips, method="chain")
    final = concatenate_videoclips([intro_clip, content_clip, outro_clip],
                                   method="chain")
    full_dur = intro_dur + total_dur + outro_dur

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
        # ultrafast ~1 dk'lık videoda 55 MB üretiyordu (Telegram limiti
        # 50 MB). veryfast + bitrate tavanı dosyayı ~40 MB altında tutar.
        preset="veryfast",
        ffmpeg_params=["-crf", "26", "-maxrate", "6M", "-bufsize", "12M",
                       "-movflags", "+faststart"],
    )

    # 8) Temp ses dosyalarını temizle
    temp_files = [intro_tts_path] + seg_tts_paths
    temp_files += presenter_jobs.get("files", [])
    if presenter_jobs.get("outro_tts"):
        temp_files.append(presenter_jobs["outro_tts"])
    for f in temp_files:
        try:
            os.remove(f)
        except Exception:
            pass

    mb = os.path.getsize(output_path) / (1024 * 1024)
    log.info(f"✅ Video hazır: {output_path} ({mb:.1f} MB)")
    return output_path
