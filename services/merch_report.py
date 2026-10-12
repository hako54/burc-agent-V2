"""
Haftalık Merch Raporu (LCW opsiyon performansı → PDF)

Haftalık yüklenen Excel'den (ör. "41.hafta_1210_.xlsx") DURUM'u seçili
olan (varsayılan: "Çok İyi" ve "İyi") opsiyonları alır, lcw.com ürün
görselleriyle birlikte Merch Alt Grup → Gelecek Dönem Ürün Klasman
kırılımında kart görünümlü bir PDF sunumu üretir.

Kullanım:
    from services.merch_report import build_report
    pdf_path, summary = build_report("41.hafta.xlsx")

Komut satırı:
    python -m services.merch_report dosya.xlsx [--gizle stok,satis] [--resimsiz]

Gizlenebilir alanlar FIELDS sözlüğündeki anahtarlardır; ayarlar
data/merch_settings.json içinde saklanır ve otomatik çalışmalarda
(web yüklemesi, Telegram'a dosya gönderme) kullanılır.
"""

import hashlib
import io
import json
import logging
import os
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
from openpyxl import load_workbook
from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

log = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "output")).resolve() / "merch"
UPLOAD_DIR = OUTPUT_DIR / "uploads"
IMG_CACHE_DIR = OUTPUT_DIR / "img_cache"
SETTINGS_FILE = Path(os.environ.get("DATA_DIR", "data")) / "merch_settings.json"

# Rapor alanları: anahtar → (etiket, Excel başlığı)
FIELDS = OrderedDict([
    ("resim",          ("Ürün Görseli",                    "Ürün Resim Linki")),
    ("option_kod",     ("Option Kod",                      "Option Kod")),
    ("urun_ad",        ("Ürün Ad",                         "Ürün Ad")),
    ("renk",           ("Renk Tanım",                      "Renk Tanım")),
    ("durum",          ("Durum",                           "DURUM")),
    ("stok",           ("Gün Sonu Reyon Stok Ort.",        "Gün Sonu Reyon Stok Ortalaması")),
    ("satis",          ("Satış Adet",                      "Satış Adet")),
    ("devir",          ("Devir Hızı",                      "Devir Hızı")),
    ("merch_alt_grup", ("Merch Alt Grup",                  "Merch Alt Grup")),
    ("klasman",        ("Gelecek Dönem Ürün Klasman",      "Gelecek Dönem Ürün Klasman")),
])

ALL_DURUM = ["Çok İyi", "İyi", "Orta", "Kötü", "Çok Kötü",
             "Minimum Mağaza Kısıtına Takıldı"]

DEFAULT_SETTINGS = {
    "durumlar": ["Çok İyi", "İyi"],
    "gizli_alanlar": [],
}

DURUM_COLORS = {
    "Çok İyi": "#0f7b3f",
    "İyi": "#5aa832",
    "Orta": "#d9a400",
    "Kötü": "#e07020",
    "Çok Kötü": "#c62828",
}
DURUM_ORDER = {d: i for i, d in enumerate(ALL_DURUM)}

# LCW renk paleti
C_BRAND = HexColor("#002f6c")
C_ACCENT = HexColor("#e30613")
C_TEXT = HexColor("#1d2433")
C_MUTED = HexColor("#6b7385")
C_LINE = HexColor("#d9dee8")
C_SOFT = HexColor("#f3f5f9")

_settings_lock = threading.Lock()


# ── Ayarlar ──────────────────────────────────────────────────────

def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return s


def save_settings(durumlar=None, gizli_alanlar=None) -> dict:
    with _settings_lock:
        s = load_settings()
        if durumlar is not None:
            s["durumlar"] = [d for d in ALL_DURUM if d in durumlar]
        if gizli_alanlar is not None:
            s["gizli_alanlar"] = [k for k in FIELDS if k in gizli_alanlar]
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        return s


# ── Yardımcılar ──────────────────────────────────────────────────

def _norm(s) -> str:
    """Türkçe harf duyarsız başlık karşılaştırması."""
    s = str(s or "").strip().replace("İ", "i").replace("I", "ı")
    return re.sub(r"\s+", " ", s.lower())


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v, decimals=0) -> str:
    if v is None:
        return "-"
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def week_label(filename: str) -> str:
    m = re.search(r"(\d{1,2})\s*\.?\s*hafta", filename or "", re.I)
    return f"{m.group(1)}. Hafta" if m else ""


def _register_fonts():
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    for reg, bold in candidates:
        if Path(reg).exists() and Path(bold).exists():
            if "MR" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("MR", reg))
                pdfmetrics.registerFont(TTFont("MR-B", bold))
            return "MR", "MR-B"
    log.warning("TTF font bulunamadı, Türkçe karakterler bozuk görünebilir")
    return "Helvetica", "Helvetica-Bold"


# ── Excel okuma ──────────────────────────────────────────────────

def read_options(xlsx_path, durumlar) -> list:
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [_norm(h) for h in next(rows)]

    idx = {}
    for key, (_, col) in FIELDS.items():
        try:
            idx[key] = header.index(_norm(col))
        except ValueError:
            idx[key] = None
    missing = [FIELDS[k][1] for k in ("option_kod", "durum") if idx[k] is None]
    if missing:
        wb.close()
        raise ValueError(f"Excel'de beklenen sütun yok: {', '.join(missing)}")

    wanted = {_norm(d) for d in durumlar}
    items = []
    for r in rows:
        def g(k):
            i = idx[k]
            return r[i] if i is not None and i < len(r) else None

        if not g("option_kod"):
            continue
        durum = str(g("durum") or "").strip()
        if _norm(durum) not in wanted:
            continue
        items.append({
            "resim": str(g("resim") or "").strip(),
            "option_kod": str(g("option_kod")).strip(),
            "urun_ad": str(g("urun_ad") or "").strip(),
            "renk": str(g("renk") or "").strip(),
            "durum": durum,
            "stok": _num(g("stok")),
            "satis": _num(g("satis")),
            "devir": _num(g("devir")),
            "merch_alt_grup": str(g("merch_alt_grup") or "-").strip(),
            "klasman": str(g("klasman") or "-").strip(),
        })
    wb.close()
    return items


# ── Görseller ────────────────────────────────────────────────────

_http = requests.Session()
_http.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Referer": "https://www.lcw.com/",
})


def _fetch_image(url: str):
    """Görseli indirir, küçültür, diske cache'ler. Hata → None."""
    if not url.startswith("http"):
        return None
    path = IMG_CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".jpg")
    if path.exists():
        return str(path)
    try:
        r = _http.get(url, timeout=20)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((300, 400))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        im.save(tmp, "JPEG", quality=82, optimize=True)
        tmp.replace(path)
        return str(path)
    except Exception as e:
        log.debug(f"Görsel indirilemedi {url}: {e}")
        return None


def fetch_images(items, workers=16, progress=None) -> int:
    urls = list({it["resim"] for it in items if it["resim"]})
    done = ok = 0
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for url, p in zip(urls, ex.map(_fetch_image, urls)):
            results[url] = p
            done += 1
            ok += bool(p)
            if progress and done % 50 == 0:
                progress(f"Görseller: {done}/{len(urls)}")
    for it in items:
        it["img_path"] = results.get(it["resim"])
    return ok


# ── PDF çizimi ───────────────────────────────────────────────────

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 26
HEADER_H = 46
FOOTER_H = 22
COLS = 6
GAP = 9
GROUP_H = 22


class _Report:
    def __init__(self, items, hidden, title, subtitle, out_path):
        self.items = items
        self.hidden = set(hidden)
        self.title = title
        self.subtitle = subtitle
        self.out_path = out_path
        self.font, self.bold = _register_fonts()
        self.show_img = "resim" not in self.hidden
        self.cols = COLS if self.show_img else COLS - 1
        self.card_w = (PAGE_W - 2 * MARGIN - (self.cols - 1) * GAP) / self.cols
        # Sayfaya 2 kart satırı + 2 grup başlığı sığacak yükseklik
        self.img_h = 126 if self.show_img else 0
        self.card_h = self.img_h + 8 + len(self._card_lines(None)) * 10.5 + 6
        # Görünür olan Merch Alt Grup / Klasman alanları gruplama başlığı olur
        self.group_keys = [k for k in ("merch_alt_grup", "klasman")
                           if k not in self.hidden]

    # Kartta gösterilecek satırlar (gizli alanlar hariç)
    def _card_lines(self, it):
        lines = []
        if "option_kod" not in self.hidden:
            lines.append(("b", it and it["option_kod"]))
        if "urun_ad" not in self.hidden:
            lines.append(("t", it and it["urun_ad"]))
        if "renk" not in self.hidden:
            lines.append(("m", it and it["renk"]))
        for key, label, dec in (("stok", "Stok Ort.", 0),
                                ("satis", "Satış Adet", 0),
                                ("devir", "Devir Hızı", 2)):
            if key not in self.hidden:
                lines.append(("kv", it and (label, _fmt(it[key], dec))))
        return lines

    # ── Sayfalama ────────────────────────────────────────────────
    def _paginate(self):
        """Blokları sayfalara yerleştirir.
        Döner: pages = [[(tip, veri, y), ...], ...], toc = [(grup, alt, sayfa)]"""
        def sort_key(it):
            return (tuple(it[k] for k in self.group_keys),
                    DURUM_ORDER.get(it["durum"], 99),
                    -(it["devir"] or 0))
        items = sorted(self.items, key=sort_key)

        top = PAGE_H - MARGIN - HEADER_H
        bottom = MARGIN + FOOTER_H
        pages, toc = [], []
        page, y = [], top
        cur_main = None

        def new_page():
            nonlocal page, y
            if page:
                pages.append(page)
            page, y = [], top

        # Grupla
        groups = OrderedDict()
        for it in items:
            groups.setdefault(tuple(it[k] for k in self.group_keys), []).append(it)

        for gkey, gitems in groups.items():
            main = gkey[0] if gkey else None
            if self.group_keys and main != cur_main:
                # Her ana grup yeni sayfada başlar
                new_page()
                cur_main = main
            label = " › ".join(gkey) if gkey else "Tüm Opsiyonlar"
            if y - GROUP_H - self.card_h < bottom:
                new_page()
            page.append(("group", (label, gitems), y))
            toc.append((gkey, len(gitems), len(pages) + 2))  # +1 kapak
            y -= GROUP_H + 4
            for i in range(0, len(gitems), self.cols):
                if y - self.card_h < bottom:
                    new_page()
                    page.append(("group", (label + "  (devam)", None), y))
                    y -= GROUP_H + 4
                page.append(("row", gitems[i:i + self.cols], y))
                y -= self.card_h + GAP
        new_page()
        return pages, toc

    # ── Çizim ────────────────────────────────────────────────────
    def _header(self, c, page_no, total, right=""):
        c.setFillColor(C_BRAND)
        c.rect(0, PAGE_H - 34, PAGE_W, 34, stroke=0, fill=1)
        c.setFillColor(C_ACCENT)
        c.rect(0, PAGE_H - 37, PAGE_W, 3, stroke=0, fill=1)
        c.setFillColor(HexColor("#ffffff"))
        c.setFont(self.bold, 13)
        c.drawString(MARGIN, PAGE_H - 22, self.title)
        c.setFont(self.font, 9)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 22, right)
        c.setFillColor(C_MUTED)
        c.setFont(self.font, 7.5)
        c.drawString(MARGIN, MARGIN - 6, self.subtitle)
        c.drawRightString(PAGE_W - MARGIN, MARGIN - 6, f"Sayfa {page_no} / {total}")

    def _fit(self, c, text, font, size, width):
        text = str(text or "")
        if c.stringWidth(text, font, size) <= width:
            return text
        while text and c.stringWidth(text + "…", font, size) > width:
            text = text[:-1]
        return text + "…"

    def _draw_group(self, c, label, gitems, y):
        c.setFillColor(C_SOFT)
        c.roundRect(MARGIN, y - GROUP_H, PAGE_W - 2 * MARGIN, GROUP_H, 3, stroke=0, fill=1)
        c.setFillColor(C_ACCENT)
        c.rect(MARGIN, y - GROUP_H, 4, GROUP_H, stroke=0, fill=1)
        c.setFillColor(C_BRAND)
        c.setFont(self.bold, 10.5)
        c.drawString(MARGIN + 12, y - 15, label)
        if gitems:
            counts = {}
            for it in gitems:
                counts[it["durum"]] = counts.get(it["durum"], 0) + 1
            txt = "   ".join(f"{d}: {n}" for d, n in
                             sorted(counts.items(), key=lambda x: DURUM_ORDER.get(x[0], 99)))
            c.setFont(self.font, 8.5)
            c.setFillColor(C_MUTED)
            c.drawRightString(PAGE_W - MARGIN - 10, y - 15,
                              f"{len(gitems)} opsiyon   ·   {txt}")

    def _draw_card(self, c, it, x, y):
        w, h = self.card_w, self.card_h
        c.setStrokeColor(C_LINE)
        c.setFillColor(HexColor("#ffffff"))
        c.setLineWidth(0.6)
        c.roundRect(x, y - h, w, h, 4, stroke=1, fill=1)
        cy = y
        if self.show_img:
            ix, iy, iw, ih = x + 4, y - 4 - self.img_h, w - 8, self.img_h
            if it.get("img_path"):
                try:
                    img = ImageReader(it["img_path"])
                    pw, ph = img.getSize()
                    s = min(iw / pw, ih / ph)
                    dw, dh = pw * s, ph * s
                    c.drawImage(img, ix + (iw - dw) / 2, iy + (ih - dh) / 2, dw, dh)
                except Exception:
                    it["img_path"] = None
            if not it.get("img_path"):
                c.setFillColor(C_SOFT)
                c.rect(ix, iy, iw, ih, stroke=0, fill=1)
                c.setFillColor(C_MUTED)
                c.setFont(self.font, 8)
                c.drawCentredString(ix + iw / 2, iy + ih / 2, "Görsel için tıklayın")
            if it["resim"].startswith("http"):
                c.linkURL(it["resim"], (ix, iy, ix + iw, iy + ih), relative=0)
            cy = iy - 4
        # Durum etiketi (görselli kartta görselin köşesinde, değilse ilk satırda)
        tx, tw_ = x + 7, w - 14
        tw_first = tw_
        if "durum" not in self.hidden:
            col = HexColor(DURUM_COLORS.get(it["durum"], "#555555"))
            c.setFont(self.bold, 7)
            bw = c.stringWidth(it["durum"], self.bold, 7) + 10
            bx = x + w - bw - 6
            by = (y - 18) if self.show_img else (y - 14)
            c.setFillColor(col)
            c.roundRect(bx, by, bw, 11, 5.5, stroke=0, fill=1)
            c.setFillColor(HexColor("#ffffff"))
            c.drawCentredString(bx + bw / 2, by + 3, it["durum"])
            if not self.show_img:
                tw_first = tw_ - bw - 4
        cy -= 10
        for n, (kind, val) in enumerate(self._card_lines(it)):
            limit = tw_first if n == 0 else tw_
            if kind == "b":
                c.setFont(self.bold, 8.5)
                c.setFillColor(C_BRAND)
                txt = self._fit(c, val, self.bold, 8.5, limit)
                c.drawString(tx, cy, txt)
                if it["resim"].startswith("http"):  # Option kod → lcw.com görseli
                    c.linkURL(it["resim"], (tx, cy - 2, tx + c.stringWidth(
                        txt, self.bold, 8.5), cy + 8), relative=0)
            elif kind == "t":
                c.setFont(self.font, 8)
                c.setFillColor(C_TEXT)
                c.drawString(tx, cy, self._fit(c, val, self.font, 8, limit))
            elif kind == "m":
                c.setFont(self.font, 7.5)
                c.setFillColor(C_MUTED)
                c.drawString(tx, cy, self._fit(c, val, self.font, 7.5, limit))
            else:
                label, v = val
                c.setFont(self.font, 7.5)
                c.setFillColor(C_MUTED)
                c.drawString(tx, cy, label)
                c.setFont(self.bold, 8)
                c.setFillColor(C_TEXT)
                c.drawRightString(tx + tw_, cy,
                                  self._fit(c, v, self.bold, 8, tw_ * 0.55))
            cy -= 10.5

    def _draw_cover(self, c, toc, total):
        self._header(c, 1, total, datetime.now().strftime("%d.%m.%Y"))
        c.setFillColor(C_BRAND)
        c.setFont(self.bold, 22)
        c.drawString(MARGIN, PAGE_H - 82, self.title)
        c.setFont(self.font, 10.5)
        c.setFillColor(C_MUTED)
        c.drawString(MARGIN, PAGE_H - 100, self.subtitle)

        # Özet kutuları
        counts = {}
        for it in self.items:
            counts[it["durum"]] = counts.get(it["durum"], 0) + 1
        boxes = [("Toplam Opsiyon", _fmt(len(self.items)), C_BRAND)]
        for d in sorted(counts, key=lambda d: DURUM_ORDER.get(d, 99)):
            boxes.append((d, _fmt(counts[d]), HexColor(DURUM_COLORS.get(d, "#555555"))))
        if "satis" not in self.hidden:
            boxes.append(("Toplam Satış Adet",
                           _fmt(sum(it["satis"] or 0 for it in self.items)), C_TEXT))
        bw = 150
        for i, (lab, val, col) in enumerate(boxes[:5]):
            bx = MARGIN + i * (bw + 10)
            c.setFillColor(C_SOFT)
            c.roundRect(bx, PAGE_H - 170, bw, 54, 5, stroke=0, fill=1)
            c.setFillColor(col)
            c.rect(bx, PAGE_H - 170, 4, 54, stroke=0, fill=1)
            c.setFont(self.bold, 18)
            c.drawString(bx + 14, PAGE_H - 145, val)
            c.setFont(self.font, 8.5)
            c.setFillColor(C_MUTED)
            c.drawString(bx + 14, PAGE_H - 161, lab)

        # İçindekiler (2-3 sütun)
        c.setFillColor(C_BRAND)
        c.setFont(self.bold, 12)
        c.drawString(MARGIN, PAGE_H - 198, "İçindekiler")
        entries = []
        last_main = None
        for gkey, n, pg in toc:
            if len(gkey) == 2 and gkey[0] != last_main:
                entries.append(("main", gkey[0], None, pg))
                last_main = gkey[0]
            name = gkey[-1] if gkey else "Tüm Opsiyonlar"
            entries.append(("sub" if len(gkey) == 2 else "main", name, n, pg))
        y0, avail = PAGE_H - 216, PAGE_H - 216 - MARGIN - FOOTER_H
        ncols = 2 if len(entries) <= 2 * int(avail / 11.5) else 3
        max_rows = max(int(avail / 11.5), -(-len(entries) // ncols))
        lh = avail / max_rows
        col_w = (PAGE_W - 2 * MARGIN - (ncols - 1) * 20) / ncols
        size = min(8.5, lh * 0.8)
        for i, (kind, name, n, pg) in enumerate(entries[:ncols * max_rows]):
            col, row = divmod(i, max_rows)
            x = MARGIN + col * (col_w + 20)
            y = y0 - row * lh
            if kind == "main":
                c.setFont(self.bold, size)
                c.setFillColor(C_BRAND)
                c.drawString(x, y, name)
            else:
                c.setFont(self.font, size)
                c.setFillColor(C_TEXT)
                c.drawString(x + 10, y, self._fit(c, name, self.font, size, col_w - 70))
                c.setFillColor(C_MUTED)
                c.drawRightString(x + col_w - 26, y, f"{n}")
            c.setFillColor(C_MUTED)
            c.setFont(self.font, size)
            c.drawRightString(x + col_w, y, str(pg))
            c.linkAbsolute("", f"p{pg}", (x, y - 2, x + col_w, y + lh - 2))

    def render(self):
        pages, toc = self._paginate()
        total = len(pages) + 1
        c = canvas.Canvas(str(self.out_path), pagesize=(PAGE_W, PAGE_H))
        c.setTitle(self.title)
        c.setAuthor("Burç Agent · Merch Raporu")
        self._draw_cover(c, toc, total)
        c.bookmarkPage("p1")
        c.addOutlineEntry("Kapak / İçindekiler", "p1", level=0)
        c.showPage()
        last_main = None
        for pi, page in enumerate(pages, start=2):
            c.bookmarkPage(f"p{pi}")
            right = ""
            for kind, data, y in page:
                if kind == "group":
                    label, gitems = data
                    right = label.replace("  (devam)", "")
                    if gitems is not None:
                        main = label.split(" › ")[0]
                        if len(self.group_keys) == 2 and main != last_main:
                            c.addOutlineEntry(main, f"p{pi}", level=0)
                            last_main = main
                        key = f"g{pi}_{int(y)}"
                        c.bookmarkHorizontal(key, 0, y + 4)
                        c.addOutlineEntry(label.split(" › ")[-1], key,
                                          level=1 if len(self.group_keys) == 2 else 0)
                    break
            self._header(c, pi, total, right)
            for kind, data, y in page:
                if kind == "group":
                    self._draw_group(c, data[0], data[1], y)
                else:
                    for i, it in enumerate(data):
                        self._draw_card(c, it, MARGIN + i * (self.card_w + GAP), y)
            c.showPage()
        c.save()
        return total


# ── Dış API ──────────────────────────────────────────────────────

def build_report(xlsx_path, source_name=None, durumlar=None, gizli_alanlar=None,
                 out_path=None, download_images=True, progress=None):
    """Excel'den PDF üretir. Ayar verilmezse kayıtlı ayarlar kullanılır.

    Döner: (pdf_path: Path, summary: dict)
    """
    xlsx_path = Path(xlsx_path)
    source_name = source_name or xlsx_path.name
    s = load_settings()
    durumlar = durumlar if durumlar is not None else s["durumlar"]
    gizli = gizli_alanlar if gizli_alanlar is not None else s["gizli_alanlar"]
    if not durumlar:
        raise ValueError("En az bir Durum seçilmeli")

    if progress:
        progress("Excel okunuyor…")
    items = read_options(xlsx_path, durumlar)
    if not items:
        raise ValueError(f"Seçilen durumlarda ({', '.join(durumlar)}) opsiyon bulunamadı")

    img_ok = 0
    if download_images and "resim" not in gizli:
        if progress:
            progress(f"{len(items)} opsiyon bulundu, görseller indiriliyor…")
        img_ok = fetch_images(items, progress=progress)
    else:
        for it in items:
            it["img_path"] = None

    week = week_label(source_name)
    title = f"LCW Opsiyon Performans Raporu{' — ' + week if week else ''}"
    subtitle = (f"Durum: {', '.join(durumlar)}   ·   Kırılım: Merch Alt Grup › "
                f"Gelecek Dönem Ürün Klasman   ·   Kaynak: {source_name}")

    if out_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w.-]+", "_", Path(source_name).stem).strip("_") or "rapor"
        out_path = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M}_{stem}.pdf"
    out_path = Path(out_path)

    if progress:
        progress("PDF oluşturuluyor…")
    pages = _Report(items, gizli, title, subtitle, out_path).render()

    summary = {
        "pdf": out_path.name,
        "kaynak": source_name,
        "hafta": week,
        "opsiyon": len(items),
        "gorsel": img_ok,
        "sayfa": pages,
        "durumlar": durumlar,
        "gizli_alanlar": gizli,
        "durum_dagilimi": {d: sum(1 for it in items if it["durum"] == d)
                           for d in durumlar},
        "merch_alt_grup": len({it["merch_alt_grup"] for it in items}),
        "klasman": len({it["klasman"] for it in items}),
        "tarih": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        out_path.with_suffix(".json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    log.info(f"📄 Merch raporu hazır: {out_path.name} "
             f"({len(items)} opsiyon, {img_ok} görsel, {pages} sayfa)")
    return out_path, summary


# ── Arka plan işi (web paneli + Telegram ortak) ──────────────────

_job = {"durum": "bos"}
_job_lock = threading.Lock()


def job_status() -> dict:
    with _job_lock:
        return dict(_job)


def start_job(xlsx_path, source_name, on_done=None, **kwargs) -> bool:
    """Raporu arka planda üretir. Zaten bir iş çalışıyorsa False döner.
    on_done(pdf_path, summary, error) iş bitince çağrılır."""
    with _job_lock:
        if _job.get("durum") == "calisiyor":
            return False
        _job.clear()
        _job.update(durum="calisiyor", kaynak=source_name, mesaj="Başlıyor…",
                    baslangic=datetime.now().isoformat(timespec="seconds"))

    def progress(msg):
        with _job_lock:
            _job["mesaj"] = msg

    def run():
        pdf, summ, err = None, None, None
        try:
            pdf, summ = build_report(xlsx_path, source_name=source_name,
                                     progress=progress, **kwargs)
            with _job_lock:
                _job.update(durum="bitti", mesaj="Hazır", sonuc=summ)
        except Exception as e:
            log.exception("Merch raporu üretilemedi")
            err = str(e)
            with _job_lock:
                _job.update(durum="hata", mesaj=err)
        if on_done:
            try:
                on_done(pdf, summ, err)
            except Exception:
                log.exception("Merch on_done hatası")

    threading.Thread(target=run, daemon=True, name="MerchReport").start()
    return True


def save_upload(data: bytes, filename: str) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]+", "_", Path(filename).name).strip("_") or "dosya.xlsx"
    path = UPLOAD_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{safe}"
    path.write_bytes(data)
    return path


def list_reports(limit=30) -> list:
    if not OUTPUT_DIR.exists():
        return []
    out = []
    for pdf in sorted(OUTPUT_DIR.glob("*.pdf"), reverse=True)[:limit]:
        info = {"pdf": pdf.name, "boyut_mb": round(pdf.stat().st_size / 1e6, 1)}
        try:
            info.update(json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        out.append(info)
    return out


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Haftalık merch PDF raporu")
    ap.add_argument("xlsx")
    ap.add_argument("-o", "--out")
    ap.add_argument("--durum", help="Virgüllü durum listesi (varsayılan: Çok İyi,İyi)")
    ap.add_argument("--gizle", help=f"Gizlenecek alanlar: {','.join(FIELDS)}")
    ap.add_argument("--resimsiz", action="store_true", help="Görselleri indirme")
    a = ap.parse_args()
    p, summ = build_report(
        a.xlsx, out_path=a.out,
        durumlar=[d.strip() for d in a.durum.split(",")] if a.durum else None,
        gizli_alanlar=[g.strip() for g in a.gizle.split(",")] if a.gizle else None,
        download_images=not a.resimsiz, progress=print)
    print(json.dumps(summ, ensure_ascii=False, indent=2))
