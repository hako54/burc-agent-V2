"""
Hikâye kartı
────────────
Yorumlara DM ile gönderilen kişiye özel burç/isim mesajını Instagram
hikâyesinde paylaşılabilecek 1080×1920 bir karta çizer.
"""

import math
import random
import time
from pathlib import Path

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
GOLD = (236, 196, 92)


def _bg(seed: int) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    c1, c2 = (58, 22, 120), (10, 5, 28)
    for y in range(H):
        for x in range(0, W):
            d = min(1.0, math.hypot(x - W * 0.5, y - H * 0.38) / (H * 0.62))
            px[x, y] = tuple(int(c1[i] * (1 - d) + c2[i] * d) for i in range(3))
    d = ImageDraw.Draw(img, "RGBA")
    rnd = random.Random(seed)
    for _ in range(220):
        x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.choice([1, 1, 2, 2, 3])
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=(255, 255, 255, rnd.randint(70, 210)))
    return img


_FONTS = ["font/Montserrat-ExtraBold.ttf", "font/Montserrat-Bold.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


def _get_font(size: int):
    for p in _FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(draw, text: str, font, max_w: int) -> list:
    from services.emoji_text import text_width
    lines, cur = [], ""
    for w in text.split():
        test = (cur + " " + w).strip()
        if text_width(draw, test, font) > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def make_card(title: str, message: str, dst: str, handle: str = "",
              subtitle: str = "SANA ÖZEL MESAJ") -> str:
    from services.emoji_text import draw_text, text_width
    from services.tr_locale import tr_upper, tr_date
    img = _bg(int(time.time()) // 3600)
    # Altın hale + çerçeve
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([240, 300, 840, 900], fill=(236, 196, 92, 60))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img.paste(glow, (0, 0), glow)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([50, 50, W - 50, H - 50], radius=48,
                        outline=GOLD + (200,), width=5)

    sf = _get_font(44)
    lab = f"✨ {subtitle} ✨"
    draw_text(img, d, ((W - text_width(d, lab, sf)) // 2, 190), lab, sf,
              GOLD + (255,))

    t = tr_upper(title)
    size = 130
    tf = _get_font(size)
    while text_width(d, t, tf) > W - 200 and size > 70:
        size -= 6
        tf = _get_font(size)
    draw_text(img, d, ((W - text_width(d, t, tf)) // 2, 300), t, tf,
              (255, 255, 255, 255))
    d.line([(W // 2 - 140, 300 + size + 40), (W // 2 + 140, 300 + size + 40)],
           fill=GOLD + (230,), width=5)

    # Mesaj: kutuya sığana kadar küçült
    box_top, box_bot = 300 + size + 110, H - 420
    for fs in (62, 58, 54, 50, 46, 42):
        mf = _get_font(fs)
        lines = _wrap_text(d, message, mf, W - 220)
        lh = int(fs * 1.38)
        if len(lines) * lh <= box_bot - box_top:
            break
    y = box_top + ((box_bot - box_top) - len(lines) * lh) // 2
    for ln in lines:
        draw_text(img, d, ((W - text_width(d, ln, mf)) // 2, y), ln, mf,
                  (255, 255, 255, 255))
        y += lh

    # Alt: tarih + paylaşım çağrısı
    df = _get_font(40)
    dt = tr_date()
    draw_text(img, d, ((W - text_width(d, dt, df)) // 2, H - 380), dt, df,
              (210, 200, 235, 255))
    cf = _get_font(46)
    cta = "Hikâyende paylaş 💜"
    d.rounded_rectangle([140, H - 300, W - 140, H - 140], radius=40,
                        fill=(20, 10, 40, 220), outline=GOLD + (255,), width=4)
    draw_text(img, d, ((W - text_width(d, cta, cf)) // 2, H - 285), cta, cf,
              (255, 255, 255, 255))
    if handle:
        hf = _get_font(40)
        ht = f"@{handle} etiketle ✨"
        draw_text(img, d, ((W - text_width(d, ht, hf)) // 2, H - 220), ht, hf,
                  GOLD + (255,))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=82, optimize=True)
    return dst
