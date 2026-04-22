"""
Görsel Çekim Servisi
Pixabay ve Pexels API'lerinden konuya uygun, dikey (9:16) görseller çeker.
"""

import io
import os
import logging
import requests
from PIL import Image, ImageEnhance

log = logging.getLogger(__name__)


def _fetch_from_pixabay(query: str, count: int = 3) -> list:
    """Pixabay'den dikey görsel URL'leri döner."""
    api_key = os.environ.get("PIXABAY_API_KEY")
    if not api_key:
        return []

    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": api_key,
                "q": query,
                "per_page": count,
                "image_type": "photo",
                "orientation": "vertical",
                "min_width": 800,
                "min_height": 1000,
                "safesearch": "true",
                "order": "popular",
            },
            timeout=15,
            verify=False,
        )
        if r.status_code == 200:
            urls = [hit.get("largeImageURL", "") for hit in r.json().get("hits", [])]
            return [u for u in urls if u]
        elif r.status_code == 429:
            log.warning("Pixabay rate limit")
    except Exception as e:
        log.warning(f"Pixabay hata ({query[:30]}): {e}")
    return []


def _fetch_from_pexels(query: str, count: int = 3) -> list:
    """Pexels'den dikey görsel URL'leri döner."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return []

    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": count, "orientation": "portrait"},
            timeout=15,
            verify=False,
        )
        if r.status_code == 200:
            photos = r.json().get("photos", [])
            return [p.get("src", {}).get("large2x", "") for p in photos if p.get("src")]
    except Exception as e:
        log.warning(f"Pexels hata ({query[:30]}): {e}")
    return []


def fetch_image_urls(queries: list, count: int = 6) -> list:
    """Verilen arama sorgularından görsel URL'leri toplar.
    Her sorgu için hem Pixabay hem Pexels dener, yeterli sayıya ulaşınca durur."""
    urls = []
    seen = set()

    for query in queries:
        if len(urls) >= count:
            break

        # Her sorgu için önce Pixabay, olmadıysa Pexels
        for source_name, source_fn in [("Pixabay", _fetch_from_pixabay),
                                       ("Pexels", _fetch_from_pexels)]:
            if len(urls) >= count:
                break
            new_urls = source_fn(query)
            for u in new_urls:
                if u and u not in seen:
                    seen.add(u)
                    urls.append(u)
                    log.info(f"  ✅ {source_name}: {query[:30]} → +1")
                    if len(urls) >= count:
                        break

    log.info(f"Toplam {len(urls)}/{count} görsel URL bulundu")
    return urls[:count]


def download_and_prepare(url: str, width: int, height: int,
                         accent_color: str = None) -> Image.Image | None:
    """URL'den görsel indirir ve belirtilen boyuta kırpar (9:16 için)."""
    try:
        r = requests.get(url, timeout=20, verify=False,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        if img.width < 200 or img.height < 200:
            return None

        img = _fit_to_aspect(img, width, height)
        img = _apply_dramatic(img, accent_color)
        return img
    except Exception as e:
        log.warning(f"Görsel indirme başarısız: {e}")
        return None


def _fit_to_aspect(img: Image.Image, w: int, h: int) -> Image.Image:
    """Siyah kenar olmadan 9:16'ya uyarla (merkezden kırp)."""
    iw, ih = img.size
    target_ratio = w / h

    if iw / ih > target_ratio:
        # Çok geniş → yüksekliğe göre scale, yanlardan kırp
        new_h = h
        new_w = int(iw * h / ih)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - w) // 2
        img = img.crop((left, 0, left + w, h))
    else:
        # Çok uzun → genişliğe göre scale, üstten-alttan kırp
        new_w = w
        new_h = int(ih * w / iw)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        top = (new_h - h) // 2
        img = img.crop((0, top, w, top + h))

    if img.size != (w, h):
        img = img.resize((w, h), Image.LANCZOS)
    return img


def _apply_dramatic(img: Image.Image, accent_hex: str = None) -> Image.Image:
    """Kontrast, doygunluk ve parlaklık ayarı + opsiyonel renk tonu overlay."""
    img = ImageEnhance.Contrast(img).enhance(1.2)
    img = ImageEnhance.Color(img).enhance(0.9)
    img = ImageEnhance.Brightness(img).enhance(0.82)

    if accent_hex:
        try:
            h = accent_hex.lstrip("#")
            ac = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
            tint = Image.new("RGB", img.size, ac)
            img = Image.blend(img, tint, 0.10)
        except Exception:
            pass
    return img


def create_fallback_image(w: int, h: int, accent_hex: str,
                          bg_hex: str, index: int = 0) -> Image.Image:
    """Görsel indirilemezse: burç rengine uygun sinematik gradyan."""
    from PIL import ImageDraw

    def hex_to_rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    try:
        bg = hex_to_rgb(bg_hex)
    except Exception:
        bg = (10, 10, 20)
    try:
        ac = hex_to_rgb(accent_hex)
    except Exception:
        ac = (200, 150, 50)

    c1 = bg
    c2 = tuple(min(255, c + 30) for c in bg)
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    for y in range(h):
        t = y / h
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Merkezî ışık halkası
    cx, cy = w // 2, h // 3 + (index * 80) % (h // 3)
    for radius in range(500, 0, -30):
        ratio = 1 - radius / 500
        ra = int(ac[0] * ratio * 0.35 + c2[0] * (1 - ratio * 0.6))
        ga = int(ac[1] * ratio * 0.35 + c2[1] * (1 - ratio * 0.6))
        ba = int(ac[2] * ratio * 0.35 + c2[2] * (1 - ratio * 0.6))
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(ra, ga, ba),
        )
    return img
