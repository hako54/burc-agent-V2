"""
Emoji destekli metin çizimi (Pillow).

Pillow bir metni tek fontla çizer; DejaVu gibi yazı fontlarında emoji
olmadığı için "💕 Aşk" gibi etiketler kutu (□) olarak çıkıyordu. Buradaki
yardımcılar metni parçalara ayırır: ana fontta glifi olmayan karakterler
renkli emoji fontundan (Noto Color Emoji) çizilip yazı boyutuna ölçeklenir.
Ana fontta bulunan semboller (♈ gibi) eskisi gibi ana fontla çizilir.
"""

import logging
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

_EMOJI_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",   # Docker/Linux
    r"C:\Windows\Fonts\seguiemj.ttf",                      # Windows
]
# Emoji'nin önüne/arkasına eklenen görünmez birleştiriciler
_INVISIBLE = {"\ufe0f", "\ufe0e", "\u200d"}


@lru_cache(maxsize=1)
def _emoji_font():
    for path in _EMOJI_FONT_CANDIDATES:
        try:
            # Noto Color Emoji bitmap bir font; sadece 109 boyutunda yüklenir
            size = 109 if "Noto" in path else 96
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    log.warning("Renkli emoji fontu bulunamadı — emoji'ler çizilmeyecek")
    return None


@lru_cache(maxsize=4096)
def _has_glyph(font, ch: str) -> bool:
    """Font bu karakteri içeriyor mu? Eksik glif .notdef kutusu olarak
    çizilir; onu bilinen eksik bir karakterle karşılaştırırız."""
    if ch.isascii():
        return True
    try:
        mask = bytes(font.getmask(ch))
        missing = bytes(font.getmask("\U0010fffd"))
        return mask != missing
    except Exception:
        return True


def split_runs(text: str, font) -> list:
    """Metni [(is_emoji, parça), ...] listesine böler."""
    runs = []
    for ch in text:
        if ch in _INVISIBLE:
            continue
        emoji = not _has_glyph(font, ch) and _emoji_font() is not None
        if runs and runs[-1][0] == emoji and not emoji:
            runs[-1] = (False, runs[-1][1] + ch)
        else:
            runs.append((emoji, ch))
    return runs


def _emoji_size(font) -> int:
    return max(8, int(getattr(font, "size", 40) * 1.05))


@lru_cache(maxsize=256)
def _emoji_image(ch: str, size: int):
    """Tek emoji'yi renkli olarak çizip size×size'a ölçekler."""
    ef = _emoji_font()
    if ef is None:
        return None
    canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((8, 8), ch, font=ef, embedded_color=True)
    bbox = canvas.getbbox()
    if not bbox:
        return None
    em = canvas.crop(bbox)
    scale = size / max(em.width, em.height)
    return em.resize((max(1, round(em.width * scale)),
                      max(1, round(em.height * scale))), Image.LANCZOS)


def text_width(draw, text: str, font) -> int:
    """draw.textbbox(...)[2] karşılığı, emoji'leri doğru genişlikle sayar."""
    x = 0
    for is_emoji, part in split_runs(text, font):
        if is_emoji:
            x += _emoji_size(font) + 2
        else:
            x += draw.textbbox((0, 0), part, font=font)[2]
    return x


def draw_text(img: Image.Image, draw, xy, text: str, font, fill,
              emoji: bool = True):
    """draw.text((x, y), text, font, fill) karşılığı. emoji=False ise
    emoji'ler çizilmez ama yerleri boş bırakılır (dış çizgi geçişleri
    için)."""
    x, y = xy
    alpha = fill[3] if len(fill) == 4 else 255
    for is_emoji, part in split_runs(text, font):
        if not is_emoji:
            draw.text((x, y), part, font=font, fill=fill)
            x += draw.textbbox((0, 0), part, font=font)[2]
            continue
        size = _emoji_size(font)
        if emoji:
            em = _emoji_image(part, size)
            if em is not None:
                # Emoji'yi yazının dikey ortasına hizala
                top, bottom = font.getbbox("Ag")[1], font.getbbox("Ag")[3]
                ey = int(y + (top + bottom) / 2 - em.height / 2)
                paste_image(img, em, (int(x + 1), ey), alpha=alpha / 255)
        x += size + 2


def paste_image(img: Image.Image, em: Image.Image, pos,
                alpha: float = 1.0):
    """RGBA görüntüyü (saydamlığı alpha ile çarpılarak) img üzerine
    yerleştirir; kenarlardan taşan kısım kırpılır."""
    if alpha <= 0:
        return
    if alpha < 0.999:
        em = em.copy()
        em.putalpha(em.getchannel("A").point(lambda a: int(a * alpha)))
    x, y = pos
    left, top = max(0, -x), max(0, -y)
    right = min(em.width, img.width - x)
    bottom = min(em.height, img.height - y)
    if right <= left or bottom <= top:
        return
    if img.mode == "RGBA":
        img.alpha_composite(em.crop((left, top, right, bottom)),
                            dest=(x + left, y + top))
    else:
        img.paste(em.crop((left, top, right, bottom)), (x + left, y + top),
                  em.crop((left, top, right, bottom)))


def is_emoji_only(text: str, font) -> bool:
    """Metin sadece (ana fontta olmayan) emoji'lerden mi oluşuyor?"""
    runs = [r for r in split_runs(text.strip(), font) if r[1].strip()]
    return bool(runs) and all(is_emoji for is_emoji, _ in runs)


def emoji_image(text: str, size: int):
    """Metindeki ilk emoji'nin size×size renkli görüntüsü (yoksa None)."""
    for ch in text:
        if ch not in _INVISIBLE and not ch.isspace():
            return _emoji_image(ch, size)
    return None
