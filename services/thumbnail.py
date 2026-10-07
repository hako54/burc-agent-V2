"""
Thumbnail Generator
Vurucu, viral, ilgi çekici YouTube thumbnail üretir.

Akış:
1. Claude'dan video içeriğine bakarak 2-4 kelimelik VURUCU bir thumbnail
   başlığı iste (videodaki başlık değil — daha kısa, ham, çarpıcı).
2. Pixabay'den uygun bir arka plan görseli çek (tema renklerine göre).
3. PIL ile arka planı koyulaştır + dev başlık metni + accent renk.

Format: 1280x720 (YouTube önerilen) veya 1080x1920 (Shorts için).
"""

import io
import os
import logging
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

from services.tr_locale import tr_upper

log = logging.getLogger(__name__)

# YouTube'un önerdiği boyutlar
THUMB_W = 1280
THUMB_H = 720

# Shorts için dikey thumbnail (9:16)
SHORTS_THUMB_W = 1080
SHORTS_THUMB_H = 1920

# Font yolu - mevcut sisteme uygun
_FONT_CANDIDATES = [
    "font/Montserrat-ExtraBold.ttf",
    "font/Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]


def _get_font(size: int):
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


def generate_thumbnail_title(content: dict, channel_type: str = "zodiac") -> str:
    """Claude'dan kısa, vurucu, viral bir thumbnail başlığı ister.
    Videoda kullanılan uzun başlıktan farklı — sadece 2-4 kelime.
    """
    from services.content import call_llm_with_fallback, parse_llm_json

    video_title = content.get("title", "")
    full_narration = content.get("full_narration", "")
    topic_label = content.get("topic_label") or content.get("main_label", "")
    main_quote = content.get("main_quote", "")

    if channel_type == "zodiac":
        sign_name = content.get("sign_name", "")
        prompt = f"""YouTube Shorts için VURUCU bir thumbnail başlığı yaz.

Video başlığı: {video_title}
Burç: {sign_name}
İçerik özeti: {full_narration[:500]}

THUMBNAIL kuralları (KRİTİK):
- 2-4 KELİME, en fazla 25 karakter
- BÜYÜK harflerle yazılacak şekilde tasarla
- Tıklatıcı, merak uyandırıcı, duygusal
- Klasik klişeler değil ("DİKKAT", "KORKUNÇ" gibi) — daha akıllı
- Burç adı dahil değil (zaten thumbnail'de görsel olacak)
- ⚠️ MUTLAKA TÜRKÇEDE GERÇEK KELİMELER kullan
- ⚠️ Asla uydurma kelimeler yapma
- ⚠️ Her kelime tam ve doğru yazım olmalı

GEÇERLİ örnekler:
- "BUGÜN TUTKUN GERİ DÖNÜYOR"
- "BU GÜN HER ŞEY DEĞİŞİR"
- "AY GÖZÜNÜ AÇTI"
- "İÇ SES UYANIYOR"
- "YENİ KAPILAR AÇILIYOR"

YANLIŞ — bunlar gibi uyduruk asla yapma:
- "TUTKKUN" ❌ (yanlış yazım)
- "GERIDND" ❌ (yarım kelime)

Sadece başlığı yaz. Türkçede gerçekten var olan kelimeleri kullan."""
    elif channel_type == "oneline":
        # OneLineADay için: ana cümlenin özünü çıkar (1-3 kelime)
        prompt = f"""OneLineADay (tek cümlelik içgörü) YouTube Shorts için
thumbnail başlığı yaz.

Ana cümle: {main_quote or video_title}
İçerik: {full_narration[:300]}

Thumbnail KISA ve VURUCU olmalı:
- 2-3 KELİME, en fazla 18 karakter
- Şiirsel, kalbe dokunan, kırılgan
- Tek bir kelime de olabilir
- Edebi tat var

Örnekler:
- "BAŞKA BİR SEN"
- "VEDA"
- "GEÇ KALDIK"
- "İÇİNDEKİ SES"
- "YALNIZLIK"
- "BUNU BİL"
- "SUS BAK"

Sadece başlığı yaz, başka hiçbir şey yazma. Tırnak da koyma."""
    else:
        # motivation
        prompt = f"""Motivasyon YouTube Shorts için VURUCU bir thumbnail başlığı yaz.

Video başlığı: {video_title}
Tema: {topic_label}
İçerik özeti: {full_narration[:500]}

THUMBNAIL kuralları (KRİTİK):
- 2-4 KELİME, en fazla 25 karakter
- BÜYÜK harflerle yazılacak şekilde tasarla
- Duygusal, yürek burkan veya çarpıcı
- Klasik klişeler değil — özgün, içe işleyen
- ⚠️ MUTLAKA TÜRKÇEDE GERÇEK KELİMELER kullan
- ⚠️ Asla uydurma, kısaltma veya hibrit kelimeler yapma
- ⚠️ Her kelime tam olmalı, yazım kuralı doğru olmalı

GEÇERLİ örnekler:
- "BUNU BİL"
- "GERÇEK ŞU"
- "SUSMA"
- "GEÇ KALMA"
- "AYNAYA BAK"
- "İÇİNDEKİ SES"
- "DURMA YÜRÜ"
- "AKAR YOLUNU BULUR"

YANLIŞ — bunlar gibi UYDURUK kelimeler YAPMA:
- "AKMAZSA KRIL" ❌ (KRIL kelimesi yok)
- "DURMSA YOLDA" ❌ (DURMSA kelimesi yok)
- "AKAR DEVAM" ❌ (eksik, anlamsız)

Sadece başlığı yaz, başka hiçbir şey yazma. Tırnak da koyma.
Türkçede gerçekten var olan kelimeleri kullan."""

    try:
        raw, provider = call_llm_with_fallback(prompt)
        title = raw.strip().strip('"\'').strip()
        title = title.split("\n")[0].strip()
        # Ek güvenlik: özel karakterler ve kötü formatları temizle
        title = title.replace("**", "").replace("##", "").replace("*", "")
        if len(title) > 30:
            title = title[:30].rstrip()

        # Şüpheli kısaltmalar/uyduruk kelime kontrolü
        # 5+ harfli ünlü/ünsüz dengesi olmayan kelime varsa fallback
        def looks_suspicious(text: str) -> bool:
            words = text.split()
            for w in words:
                w_clean = w.strip(".,!?:;").lower()
                if len(w_clean) < 3:
                    continue
                # Türkçe ünlü harfleri
                vowels = set("aeıioöuü")
                vowel_count = sum(1 for c in w_clean if c in vowels)
                # Bir kelimede en az 1 ünlü olmalı (uzun kelimelerde 2+)
                if len(w_clean) >= 5 and vowel_count == 0:
                    return True
                if len(w_clean) >= 4 and vowel_count == 0:
                    return True
            return False

        if looks_suspicious(title):
            log.warning(f"Şüpheli thumbnail başlığı '{title}' - fallback")
            words = (video_title or topic_label or "İLHAM").split()[:3]
            title = tr_upper(" ".join(words))[:25]

        if not title:
            title = "BUGÜN İÇİN"
        log.info(f"[{provider}] Thumbnail title: {title}")
        return tr_upper(title)
    except Exception as e:
        log.warning(f"Thumbnail title üretilemedi: {e}, fallback kullanılıyor")
        words = (video_title or topic_label or "İLHAM").split()[:3]
        return tr_upper(" ".join(words))[:25]


def _fetch_from_pexels(query: str, target_w: int, target_h: int):
    """Pexels'dan görsel çek. PEXELS_API_KEY env'de olmalı."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return None

    is_vertical = target_h > target_w
    orientation = "portrait" if is_vertical else "landscape"

    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={
                "query": query,
                "per_page": 5,
                "orientation": orientation,
                "size": "large",
            },
            timeout=15, verify=False,
        )
        if r.status_code == 200:
            photos = r.json().get("photos", [])
            if photos:
                # En büyük versiyonu al
                src = photos[0].get("src", {})
                url = src.get("large2x") or src.get("large") or src.get("original")
                if url:
                    ir = requests.get(url, timeout=20, verify=False,
                                      headers={"User-Agent": "Mozilla/5.0"})
                    if ir.status_code == 200:
                        return Image.open(io.BytesIO(ir.content)).convert("RGB")
    except Exception as e:
        log.warning(f"Pexels ({query}): {e}")
    return None


def _fetch_from_pixabay(query: str, target_w: int, target_h: int):
    """Pixabay'den görsel çek."""
    api_key = os.environ.get("PIXABAY_API_KEY")
    if not api_key:
        return None

    is_vertical = target_h > target_w
    orientation = "vertical" if is_vertical else "horizontal"

    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": api_key,
                "q": query,
                "per_page": 5,
                "image_type": "photo",
                "orientation": orientation,
                "min_width": 720 if is_vertical else 1280,
                "safesearch": "true",
            },
            timeout=15, verify=False,
        )
        if r.status_code == 200:
            hits = r.json().get("hits", [])
            if hits:
                url = hits[0].get("largeImageURL")
                if url:
                    ir = requests.get(url, timeout=20, verify=False,
                                      headers={"User-Agent": "Mozilla/5.0"})
                    if ir.status_code == 200:
                        return Image.open(io.BytesIO(ir.content)).convert("RGB")
    except Exception as e:
        log.warning(f"Pixabay ({query}): {e}")
    return None


def _fetch_background_image(queries: list,
                            accent_hex: str,
                            bg_hex: str,
                            target_w: int = None,
                            target_h: int = None) -> Image.Image:
    """Pexels (öncelikli) ve Pixabay'den uygun aspect görsel çeker.
    Olmazsa fallback gradient.
    Pexels portrait stüdyo görselleri Pixabay'den daha kaliteli."""
    tw = target_w or THUMB_W
    th = target_h or THUMB_H

    # Önce her query için Pexels (kaliteli portreler), sonra Pixabay
    for q in (queries or [])[:3]:
        img = _fetch_from_pexels(q, tw, th)
        if img:
            log.info(f"  ✓ Pexels'tan: {q}")
            return img
        img = _fetch_from_pixabay(q, tw, th)
        if img:
            log.info(f"  ✓ Pixabay'den: {q}")
            return img

    log.warning("Hiçbir kaynak görsel sağlamadı, gradient kullanılıyor")
    return _gradient_image(accent_hex, bg_hex, w=tw, h=th)


def _gradient_image(accent_hex: str, bg_hex: str,
                    w: int = None, h: int = None) -> Image.Image:
    """Accent renkten bg renge gradient."""
    tw = w or THUMB_W
    th = h or THUMB_H
    try:
        ac = _hex_to_rgb(accent_hex)
    except Exception:
        ac = (200, 150, 50)
    try:
        bg = _hex_to_rgb(bg_hex)
    except Exception:
        bg = (15, 10, 30)

    img = Image.new("RGB", (tw, th))
    draw = ImageDraw.Draw(img)
    for y in range(th):
        t = y / th
        r = int(bg[0] * (1 - t) + ac[0] * t * 0.5)
        g = int(bg[1] * (1 - t) + ac[1] * t * 0.5)
        b = int(bg[2] * (1 - t) + ac[2] * t * 0.5)
        draw.line([(0, y), (tw, y)], fill=(r, g, b))
    return img


def _crop_to_aspect(img: Image.Image, target_w: int = None,
                    target_h: int = None) -> Image.Image:
    """Görseli hedef boyuta uyarla (merkezden kırp)."""
    tw = target_w or THUMB_W
    th = target_h or THUMB_H
    iw, ih = img.size
    target_ratio = tw / th

    if iw / ih > target_ratio:
        new_h = th
        new_w = int(iw * th / ih)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - tw) // 2
        img = img.crop((left, 0, left + tw, th))
    else:
        new_w = tw
        new_h = int(ih * tw / iw)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        top = (new_h - tw) // 2
        img = img.crop((0, top, tw, top + th))

    return img.resize((tw, th), Image.LANCZOS)


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


def _add_dramatic_overlay(img: Image.Image, accent_hex: str) -> Image.Image:
    """Görseli koyulaştır + accent renk tint + vignette."""
    iw, ih = img.size
    img = ImageEnhance.Contrast(img).enhance(1.3)
    img = ImageEnhance.Brightness(img).enhance(0.55)
    img = ImageEnhance.Color(img).enhance(0.85)
    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))

    try:
        ac = _hex_to_rgb(accent_hex)
        tint = Image.new("RGB", img.size, ac)
        img = Image.blend(img, tint, 0.18)
    except Exception:
        pass

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(ih):
        alpha = 0
        if y > ih * 0.55:
            alpha = int(((y - ih * 0.55) / (ih * 0.45)) * 180)
        draw.line([(0, y), (iw, y)], fill=(0, 0, 0, alpha))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay)
    return img.convert("RGB")


def _draw_dramatic_text(img: Image.Image, text: str,
                        accent_hex: str,
                        sign_emoji: str = "",
                        sign_name: str = "") -> Image.Image:
    """Üst-orta'da dev başlık metni. Alt'ta küçük etiket."""
    iw, ih = img.size
    img = img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        ac = _hex_to_rgb(accent_hex)
    except Exception:
        ac = (255, 200, 80)

    text = tr_upper(text.strip())
    word_count = len(text.split())
    char_count = len(text)

    # Boyut belirle - dikey için biraz daha büyük
    is_vertical = ih > iw
    if char_count <= 10 and word_count <= 2:
        font_size = 220 if is_vertical else 180
    elif char_count <= 15:
        font_size = 180 if is_vertical else 150
    elif char_count <= 22:
        font_size = 140 if is_vertical else 120
    else:
        font_size = 110 if is_vertical else 95

    font = _get_font(font_size)
    max_w = iw - 120

    while font_size > 60:
        lines = _wrap_text(draw, text, font, max_w)
        line_h = int(font_size * 1.05)
        total_h = line_h * len(lines)
        if total_h <= ih * 0.6 and len(lines) <= 3:
            break
        font_size -= 10
        font = _get_font(font_size)

    lines = _wrap_text(draw, text, font, max_w)
    line_h = int(font_size * 1.05)
    total_h = line_h * len(lines)

    start_y = (ih - total_h) // 2 - 20

    for i, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=font)
        lw = bb[2] - bb[0]
        x = (iw - lw) // 2
        y = start_y + i * line_h

        outline_w = max(4, font_size // 25)
        for ox in range(-outline_w, outline_w + 1, 2):
            for oy in range(-outline_w, outline_w + 1, 2):
                if ox == 0 and oy == 0:
                    continue
                draw.text((x + ox, y + oy), line, font=font,
                          fill=(0, 0, 0, 230))

        draw.text((x, y), line, font=font,
                  fill=(255, 250, 230, 255))

        if i == len(lines) - 1:
            ul_y = y + font_size + 5
            ul_w = min(lw * 0.7, max_w * 0.5)
            ul_x = (iw - ul_w) // 2
            draw.rectangle(
                [ul_x, ul_y, ul_x + ul_w, ul_y + 8],
                fill=(*ac, 255),
            )

    if sign_emoji or sign_name:
        label_text = f"{sign_emoji} {sign_name}".strip() if sign_emoji \
            else sign_name
        if label_text:
            lf = _get_font(48)
            lb = draw.textbbox((0, 0), label_text, font=lf)
            lw = lb[2]
            lh = lb[3]
            pad = 24
            box_x = iw - lw - pad * 2 - 30
            box_y = ih - lh - pad * 2 - 30
            box_x2 = box_x + lw + pad * 2
            box_y2 = box_y + lh + pad * 2
            draw.rounded_rectangle(
                [box_x, box_y, box_x2, box_y2],
                radius=20, fill=(0, 0, 0, 180),
                outline=(*ac, 255), width=4,
            )
            draw.text((box_x + pad, box_y + pad - 5), label_text,
                      font=lf, fill=(*ac, 255))

    result = Image.alpha_composite(img, overlay)
    return result.convert("RGB")


def generate_thumbnail(content: dict, output_path: str,
                       channel_type: str = "zodiac",
                       vertical: bool = False) -> Optional[str]:
    """Tam akış: thumbnail üret ve kaydet. Dosya yolunu döner.

    vertical=True ise 1080x1920 (Shorts/portre) thumbnail üretir.
    """
    try:
        title = generate_thumbnail_title(content, channel_type)
        log.info(f"🎨 Thumbnail başlığı: {title} "
                 f"({'dikey' if vertical else 'yatay'})")

        accent = content.get("accent_color", "#d4af37")
        bg = content.get("background_color", "#0f0c1f")

        if vertical:
            tw, th = SHORTS_THUMB_W, SHORTS_THUMB_H
        else:
            tw, th = THUMB_W, THUMB_H

        # Motivasyon kanalı için kadın yüzü öne çıksın
        if channel_type == "motivation":
            face_queries = content.get("face_queries", [])
            if face_queries:
                queries = face_queries + content.get("pexels_queries", [])
            else:
                queries = ["woman portrait emotional"] + \
                          content.get("pexels_queries", [])
        else:
            queries = content.get("pexels_queries", [])

        bg_img = _fetch_background_image(queries, accent, bg, tw, th)
        bg_img = _crop_to_aspect(bg_img, tw, th)

        bg_img = _add_dramatic_overlay(bg_img, accent)

        sign_emoji = (content.get("sign_symbol")
                      or content.get("main_icon", ""))
        sign_name = (content.get("sign_name")
                     or content.get("main_label", ""))
        thumb_img = _draw_dramatic_text(bg_img, title, accent,
                                        sign_emoji, sign_name)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        thumb_img.save(output_path, "JPEG", quality=85, optimize=True)

        size_kb = os.path.getsize(output_path) / 1024
        log.info(f"✅ Thumbnail: {output_path} ({size_kb:.0f} KB)")
        return output_path
    except Exception as e:
        log.exception(f"Thumbnail üretilemedi: {e}")
        return None
