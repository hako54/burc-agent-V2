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


def prepend_cover(video_path: str, cover_path: str,
                  duration: float = 0.5) -> str:
    """Kapağı videonun başına kısa sabit kare olarak ekler (yerinde).
    YouTube Shorts akışta yüklenen küçük resmi değil videodan bir kareyi
    gösterdiği için ilk kare kapak olsun diye."""
    from moviepy.editor import (ImageClip, CompositeAudioClip,
                                concatenate_videoclips)
    src = VideoFileClip(video_path)
    still = ImageClip(np.asarray(Image.open(cover_path).convert("RGB")
                                 .resize((W, H)))).set_duration(duration)
    out = concatenate_videoclips([still, src.without_audio()])
    if src.audio is not None:
        out = out.set_audio(CompositeAudioClip(
            [src.audio.set_start(duration)]).set_duration(out.duration))
    tmp = str(Path(video_path).with_suffix(".cover.mp4"))
    out.write_videofile(tmp, fps=FPS, codec="libx264", audio_codec="aac",
                        logger=None, threads=4, preset="veryfast",
                        ffmpeg_params=["-crf", "26", "-maxrate", "6M",
                                       "-bufsize", "12M", "-pix_fmt",
                                       "yuv420p", "-movflags", "+faststart"])
    src.close()
    os.replace(tmp, video_path)
    return video_path


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


def make_compilation(parts: list, dst: str,
                     cta: str = "Tam yorumlar YouTube'da 👉 Link profilde"
                     ) -> str:
    """[(video_yolu, kesim_saniyesi), ...] → tek Reels. Her burcun
    açılışı + hook cümlesi arka arkaya; sonda YouTube çağrısı."""
    from moviepy.editor import concatenate_videoclips
    srcs, subs = [], []
    for path, cut in parts:
        c = VideoFileClip(path)
        srcs.append(c)
        sub = c.subclip(0, min(cut or c.duration, c.duration))
        if sub.audio is not None:
            sub = sub.set_audio(sub.audio.audio_fadein(0.1)
                                .audio_fadeout(0.25))
        subs.append(sub)
    if not subs:
        raise ValueError("Birleştirilecek video yok")
    full = concatenate_videoclips(subs, method="chain")

    layer = _text_block(cta, 70, W - 160, (255, 250, 235, 255), int(H * 0.80))
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    over.alpha_composite(Image.new("RGBA", (W, 260), (0, 0, 0, 150)),
                         (0, int(H * 0.80) - 130))
    over.alpha_composite(layer)
    arr = np.asarray(over).astype(np.float32)
    rgb, alpha = arr[..., :3], arr[..., 3:4] / 255.0
    start = max(0.0, full.duration - 3.0)

    def fx(get_frame, t):
        fr = get_frame(t)
        if t < start:
            return fr
        k = alpha * _ease_out((t - start) / 0.4)
        return (fr * (1 - k) + rgb * k).astype(np.uint8)

    out = full.fl(fx)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    out.write_videofile(dst, fps=FPS, codec="libx264", audio_codec="aac",
                        logger=None, threads=4, preset="veryfast",
                        ffmpeg_params=["-crf", "24", "-pix_fmt", "yuv420p",
                                       "-movflags", "+faststart"])
    for c in srcs:
        c.close()
    log.info(f"📸 Günlük burç derlemesi: {dst} ({full.duration:.1f}s)")
    return dst


def _cover_base(frame_path: str, accent_hex: str) -> Image.Image:
    """Astrolog karesi (yoksa renkli zemin), altı okunaklılık için koyu."""
    from services.video import _fit_cover
    if frame_path and os.path.exists(frame_path):
        base = Image.fromarray(_fit_cover(np.asarray(
            Image.open(frame_path).convert("RGB")))).convert("RGBA")
    else:
        base = create_fallback_image(W, H, accent_hex or "#d4af37",
                                     "#120a1f", 0).convert("RGBA")
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(H):
        a = 0 if y < H * 0.45 else int(215 * (y - H * 0.45) / (H * 0.55))
        sd.line([(0, y), (W, y)], fill=(8, 4, 18, a))
    base.alpha_composite(shade)
    return base


def _pill(base: Image.Image, label: str, size: int, y: int, ac) -> None:
    d = ImageDraw.Draw(base)
    lf = _get_font(size)
    lw = text_width(d, label, lf)
    pad = size * 3 // 4
    d.rounded_rectangle([(W - lw) // 2 - pad, y, (W + lw) // 2 + pad,
                         y + int(size * 1.85)],
                        radius=size, fill=(10, 6, 20, 180),
                        outline=ac + (255,), width=4)
    draw_text(base, d, ((W - lw) // 2, y + size // 3), label, lf,
              ac + (255,))


def make_daily_cover(frame_path: str, title: str, date_text: str,
                     symbols: str, accent_hex: str, dst: str) -> str:
    """Dikey Reels kapağı: astrolog + günün başlığı + burç sembolleri."""
    ac = _hex_to_rgb(accent_hex or "#d4af37")
    base = _cover_base(frame_path, accent_hex)
    _pill(base, "GÜNLÜK BURÇ YORUMU", 46, 120, ac)
    base.alpha_composite(_text_block(title, 112, W - 120,
                                     (255, 250, 235, 255), int(H * 0.66)))
    base.alpha_composite(_text_block(symbols, 84, W - 120, ac + (255,),
                                     int(H * 0.82)))
    base.alpha_composite(_text_block(date_text, 52, W - 120,
                                     (255, 255, 255, 235), int(H * 0.89)))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(dst, "JPEG", quality=90)
    return dst


def make_sign_cover(frame_path: str, sign_name: str, symbol: str,
                    hook: str, date_text: str, accent_hex: str,
                    dst: str) -> str:
    """Tek burç Reels kapağı: astrolog + büyük burç adı + günün vurucu
    cümlesi (hook) + tarih. Profil ızgarasında (3:4 orta kesit) burç adı
    ve hook görünür kalır."""
    from services.tr_locale import tr_upper
    ac = _hex_to_rgb(accent_hex or "#d4af37")
    base = _cover_base(frame_path, accent_hex)
    # Burcun rengiyle çerçeve: ızgarada her burç ayrı renkte görünür
    ImageDraw.Draw(base).rounded_rectangle(
        [24, 24, W - 25, H - 25], radius=48, outline=ac + (255,), width=12)
    _pill(base, date_text, 44, 250, ac)
    base.alpha_composite(_text_block(
        f"{symbol} {tr_upper(sign_name)}".strip(), 150, W - 100,
        ac + (255,), int(H * 0.56)))
    if hook:
        base.alpha_composite(_text_block(tr_upper(hook), 96, W - 110,
                                         (255, 250, 235, 255),
                                         int(H * 0.72)))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(dst, "JPEG", quality=90)
    return dst
