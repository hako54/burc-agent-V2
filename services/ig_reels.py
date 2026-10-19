"""
Instagram'a özel yazılı Reels (manifest, numeroloji…)
────────────────────────────────────────────────────
Seslendirme yok: arka planda yavaş hareket eden görseller, ekranda tek tek
beliren büyük cümleler ve telifsiz fon müziği (igmusic/). Ayrıca burç
videolarının Instagram için kısa (vurucu) kesitini üretir.
"""

import os
import random
import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from moviepy.editor import (VideoClip, VideoFileClip, AudioFileClip,
                            concatenate_audioclips)

from services.emoji_text import draw_text, text_width
from services.images import (fetch_image_urls, download_and_prepare,
                             create_fallback_image)
from services.video import (W, H, FPS, _get_font, _ken_burns, _hex_to_rgb,
                            _ease_out, _wrap_lines)

log = logging.getLogger(__name__)

MUSIC_DIR = Path(__file__).resolve().parent.parent / "igmusic"
TITLE_DUR = 2.2
LINE_DUR = 3.4
OUTRO_DUR = 2.8


def pick_music(prefer: str = "") -> str:
    files = sorted(MUSIC_DIR.glob("*.mp3"))
    if not files:
        return ""
    pref = [f for f in files if prefer and prefer in f.stem]
    return str(random.choice(pref or files))


def _outlined(layer, draw, xy, text, font, fill, ow):
    x, y = xy
    for ox in range(-ow, ow + 1, 2):
        for oy in range(-ow, ow + 1, 2):
            if ox or oy:
                draw_text(layer, draw, (x + ox, y + oy), text, font,
                          (0, 0, 0, 255), emoji=False)
    draw_text(layer, draw, (x, y), text, font, fill)


def _text_block(text: str, size: int, max_w: int, fill, y_center: int):
    """Ortalanmış, çok satırlı, dış çizgili metin katmanı (RGBA)."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    while True:
        font = _get_font(size)
        lines = _wrap_lines(draw, text, font, max_w)
        if (len(lines) <= 4 and all(text_width(draw, ln, font) <= max_w
                                    for ln in lines)) or size <= 54:
            break
        size -= 6
    lh = int(size * 1.18)
    y = y_center - lh * len(lines) // 2
    for ln in lines:
        x = (W - text_width(draw, ln, font)) // 2
        _outlined(layer, draw, (x, y), ln, font, fill, max(3, size // 22))
        y += lh
    return layer


def _blend(base: Image.Image, layer: Image.Image, alpha: float):
    if alpha <= 0:
        return
    if alpha < 0.999:
        layer = layer.copy()
        layer.putalpha(layer.getchannel("A").point(lambda a: int(a * alpha)))
    base.alpha_composite(layer)


def render_text_reel(title: str, lines: list, visual_queries: list,
                     output_path: str, accent_hex: str = "#d4af37",
                     outro: str = "Kaydet 🔖 Her gün tekrar et ✨",
                     music_hint: str = "") -> str:
    """Başlık kartı → cümleler tek tek → kapanış. Fon müzikli."""
    ac = _hex_to_rgb(accent_hex)
    lines = [ln.strip() for ln in lines if ln and ln.strip()][:6]
    total = TITLE_DUR + LINE_DUR * len(lines) + OUTRO_DUR

    # Görseller (3 tane, sırayla, yumuşak geçişli)
    urls = fetch_image_urls(visual_queries or ["golden light abstract"],
                            count=5)
    random.shuffle(urls)
    imgs = []
    for u in urls:
        im = download_and_prepare(u, W, H, accent_hex)
        if im:
            imgs.append(np.asarray(im.convert("RGB")))
        if len(imgs) >= 3:
            break
    while len(imgs) < 3:
        imgs.append(np.asarray(create_fallback_image(
            W, H, accent_hex, "#120a1f", len(imgs)).convert("RGB")))
    seg = total / len(imgs)

    # Sabit katmanlar (önbellek)
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(H):
        a = 95 + int(70 * abs(y - H / 2) / (H / 2))
        sd.line([(0, y), (W, y)], fill=(8, 4, 18, a))
    head = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(head)
    hf = _get_font(50)
    tw = text_width(hd, title, hf)
    hd.rounded_rectangle([(W - tw) // 2 - 36, 170, (W + tw) // 2 + 36, 262],
                         radius=40, fill=(10, 6, 20, 170),
                         outline=ac + (255,), width=4)
    draw_text(head, hd, ((W - tw) // 2, 186), title, hf, ac + (255,))
    title_big = _text_block(title, 110, W - 140, ac + (255,), H // 2)
    line_layers = [_text_block(ln, 92, W - 150, (255, 250, 235, 255),
                               int(H * 0.5)) for ln in lines]
    outro_layer = _text_block(outro, 80, W - 160, ac + (255,), int(H * 0.5))

    def make_frame(t):
        i = min(len(imgs) - 1, int(t // seg))
        local = t - i * seg
        fr = _ken_burns(imgs[i], local, seg, i % 2 == 0, "center")
        # Görseller arası 0.6 sn geçiş
        if i + 1 < len(imgs) and local > seg - 0.6:
            nxt = _ken_burns(imgs[i + 1], 0, seg, (i + 1) % 2 == 0, "center")
            k = (local - (seg - 0.6)) / 0.6
            fr = (fr * (1 - k) + nxt * k).astype(np.uint8)
        img = Image.fromarray(fr).convert("RGBA")
        img.alpha_composite(shade)
        if t < TITLE_DUR:
            _blend(img, title_big, min(_ease_out(t / 0.4),
                                       (TITLE_DUR - t) / 0.3))
        else:
            _blend(img, head, _ease_out((t - TITLE_DUR) / 0.4))
            j = int((t - TITLE_DUR) // LINE_DUR)
            if j < len(lines):
                lt = t - TITLE_DUR - j * LINE_DUR
                _blend(img, line_layers[j],
                       min(_ease_out(lt / 0.45), (LINE_DUR - lt) / 0.35, 1))
            else:
                _blend(img, outro_layer, _ease_out(
                    (t - TITLE_DUR - LINE_DUR * len(lines)) / 0.45))
        return np.asarray(img.convert("RGB"))

    clip = VideoClip(make_frame, duration=total)
    music = pick_music(music_hint)
    if music:
        a = AudioFileClip(music)
        if a.duration < total:
            a = concatenate_audioclips([a] * (int(total // a.duration) + 1))
        a = a.subclip(0, total).audio_fadein(0.8).audio_fadeout(1.5)
        clip = clip.set_audio(a.volumex(0.9))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    clip.write_videofile(output_path, fps=FPS, codec="libx264",
                         audio_codec="aac", logger=None, threads=4,
                         preset="veryfast",
                         ffmpeg_params=["-crf", "24", "-pix_fmt", "yuv420p",
                                        "-movflags", "+faststart"])
    log.info(f"📸 Instagram Reels hazır: {output_path} ({total:.1f}s)")
    return output_path


def make_short_cut(src: str, dst: str, cut_at: float,
                   cta: str = "Devamı YouTube'da 👉 Link profilde") -> str:
    """Burç videosunun Instagram için kısa (vurucu) kesiti: baştan cut_at
    saniyeye kadar; son 2.5 sn'de 'devamı YouTube'da' çağrısı."""
    src_clip = VideoFileClip(src)
    end = min(cut_at, src_clip.duration)
    base = src_clip.subclip(0, end)
    layer = _text_block(cta, 70, W - 160, (255, 250, 235, 255), int(H * 0.80))
    band = Image.new("RGBA", (W, 260), (0, 0, 0, 150))
    full = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    full.alpha_composite(band, (0, int(H * 0.80) - 130))
    full.alpha_composite(layer)
    arr = np.asarray(full).astype(np.float32)
    rgb, alpha = arr[..., :3], arr[..., 3:4] / 255.0
    start = max(0.0, end - 2.5)

    def fx(get_frame, t):
        fr = get_frame(t)
        if t < start:
            return fr
        k = alpha * _ease_out((t - start) / 0.4)
        return (fr * (1 - k) + rgb * k).astype(np.uint8)

    out = base.fl(fx)
    if out.audio is not None:
        out = out.set_audio(out.audio.audio_fadeout(0.6))
    out.write_videofile(dst, fps=FPS, codec="libx264", audio_codec="aac",
                        logger=None, threads=4, preset="veryfast",
                        ffmpeg_params=["-crf", "24", "-pix_fmt", "yuv420p",
                                       "-movflags", "+faststart"])
    src_clip.close()
    return dst
