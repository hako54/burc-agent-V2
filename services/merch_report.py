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
    ("cluster",        ("Cluster",                         "Cluster")),
    ("kumas",          ("Kumaş",                           "KUMAŞ-MALZEME TİPİ")),
    ("bitim",          ("Bitim İşlemi",                    "KUMAŞ-ÜRÜN BİTİM İŞLEMİ")),
    ("paca",           ("Paça Detayı",                     "PAÇA DETAYI")),
    ("yaka",           ("Yaka Tipi",                       "YAKA TİPİ")),
    ("stok",           ("Gün Sonu Reyon Stok Ort.",        "Gün Sonu Reyon Stok Ortalaması")),
    ("satis",          ("Satış Adet",                      "Satış Adet")),
    ("devir",          ("Devir Hızı",                      "Devir Hızı")),
    ("merch_alt_grup", ("Merch Alt Grup",                  "Merch Alt Grup")),
    ("klasman",        ("Gelecek Dönem Ürün Klasman",      "Gelecek Dönem Ürün Klasman")),
])

BUYER_COL = "Gelecek Dönem Buyer Grup"

# Excel sütunu olmayan ama gizlenebilen bölümler
HIDE_EXTRA = OrderedDict([("uyari", "RANGE Uyarıları")])
HIDEABLE = list(HIDE_EXTRA) + list(FIELDS)

# RANGE kontrol dosyasından (Option Kod ile) gelen alanlar
RANGE_KEYS = ("kumas", "bitim", "paca", "yaka")


VIEW_KEYS = ("buyer", "merch_alt_grup", "klasman", "cluster", "durum")


def default_view(items, varsayilan) -> list:
    """Rapor açılış filtresini uygular (HTML'deki ilk görünümle aynı).
    Bir gruptaki değerlerin hiçbiri veride yoksa o grup filtrelenmez."""
    out = items
    for k in VIEW_KEYS:
        want = {_norm(v) for v in (varsayilan or {}).get(k) or []}
        have = {_norm(it[k] or "-") for it in out}
        if want & have:
            out = [it for it in out if _norm(it[k] or "-") in want]
    return out


def range_required(klasman: str) -> list:
    """Klasmana göre RANGE'de dolu olması gereken alanlar."""
    k = _norm(klasman)
    keys = ["kumas", "bitim"]
    if "pantolon" in k:
        keys.append("paca")
    if "hırka" in k or "hirka" in k:
        keys.append("yaka")
    return keys


ALL_DURUM = ["Çok İyi", "İyi", "Orta", "Kötü", "Çok Kötü",
             "Minimum Mağaza Kısıtına Takıldı"]

DEFAULT_SETTINGS = {
    # Tüm durumlar alınır; rapor içinden filtrelenir
    "durumlar": list(ALL_DURUM),
    "gizli_alanlar": [],
    # Boş liste = tüm buyer gruplar
    "buyer_gruplar": [],
    # Klasman adında geçen kelimeler (ör. HIRKA → "KEY ORME HIRKA SET"); boş = tümü
    "klasman_kelimeler": [],
    # Boş liste = tüm clusterlar (ör. ["K"] sadece K cluster)
    "clusterlar": [],
    # Rapor açılışında seçili gelen filtreler (rapor yine tüm ürünleri içerir;
    # kutucuklardan değiştirilebilir). Değer veride yoksa o grup "Tümü" açılır.
    "rapor_varsayilan": {
        "buyer": ["ÖRME BASIC", "ÖRME", "ÖRME SET"],
        "durum": ["Çok İyi", "İyi"],
        "cluster": ["K"],
        "merch_alt_grup": ["BUC"],
        "klasman": [],
    },
    # Büyük, detaylı görselli kartlar (sayfada 4 ürün) / normal (12 ürün)
    "buyuk_gorsel": True,
}

DURUM_COLORS = {
    "Çok İyi": "#0f7b3f",
    "İyi": "#5aa832",
    "Orta": "#d9a400",
    "Kötü": "#e07020",
    "Çok Kötü": "#c62828",
    "Minimum Mağaza Kısıtına Takıldı": "#7a7f8c",
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


def save_settings(durumlar=None, gizli_alanlar=None, buyer_gruplar=None,
                  buyuk_gorsel=None, klasman_kelimeler=None, clusterlar=None) -> dict:
    with _settings_lock:
        s = load_settings()
        if durumlar is not None:
            s["durumlar"] = [d for d in ALL_DURUM if d in durumlar]
        if gizli_alanlar is not None:
            s["gizli_alanlar"] = [k for k in HIDEABLE if k in gizli_alanlar]
        if buyer_gruplar is not None:
            s["buyer_gruplar"] = [b.strip() for b in buyer_gruplar if b.strip()]
        if klasman_kelimeler is not None:
            s["klasman_kelimeler"] = [k.strip() for k in klasman_kelimeler if k.strip()]
        if clusterlar is not None:
            s["clusterlar"] = [c.strip() for c in clusterlar if c.strip()]
        if buyuk_gorsel is not None:
            s["buyuk_gorsel"] = bool(buyuk_gorsel)
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

def read_options(xlsx_path, durumlar, buyer_gruplar=None, klasman_kelimeler=None,
                 clusterlar=None) -> list:
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [_norm(h) for h in next(rows)]

    idx = {}
    for key, (_, col) in FIELDS.items():
        idx[key] = header.index(_norm(col)) if _norm(col) in header else None
    missing = [FIELDS[k][1] for k in ("option_kod", "durum") if idx[k] is None]
    if missing:
        wb.close()
        raise ValueError(f"Excel'de beklenen sütun yok: {', '.join(missing)}")
    buyer_i = header.index(_norm(BUYER_COL)) if _norm(BUYER_COL) in header else None
    if buyer_gruplar and buyer_i is None:
        wb.close()
        raise ValueError(f"Excel'de beklenen sütun yok: {BUYER_COL}")
    wanted_buyer = {_norm(b) for b in buyer_gruplar or []}
    klasman_words = [_norm(k) for k in klasman_kelimeler or []]
    wanted_cluster = {_norm(c) for c in clusterlar or []}

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
        buyer = str(r[buyer_i] or "").strip() if buyer_i is not None else ""
        if wanted_buyer and _norm(buyer) not in wanted_buyer:
            continue
        if klasman_words and not any(w in _norm(g("klasman")) for w in klasman_words):
            continue
        if wanted_cluster and _norm(g("cluster")) not in wanted_cluster:
            continue
        items.append({
            "resim": str(g("resim") or "").strip(),
            "option_kod": str(g("option_kod")).strip(),
            "urun_ad": str(g("urun_ad") or "").strip(),
            "renk": str(g("renk") or "").strip(),
            "durum": durum,
            "cluster": str(g("cluster") or "").strip(),
            "buyer": buyer,
            "stok": _num(g("stok")),
            "satis": _num(g("satis")),
            "devir": _num(g("devir")),
            "merch_alt_grup": str(g("merch_alt_grup") or "-").strip(),
            "klasman": str(g("klasman") or "-").strip(),
        })
    wb.close()
    return items


# ── RANGE kontrol dosyası ────────────────────────────────────────

RANGE_FILE = Path(os.environ.get("DATA_DIR", "data")) / "merch_range.xlsx"


def _opt_key(code) -> str:
    """'W6AT82Z8-CVL' ile 'W6AT82Z8CVL' aynı kabul edilir."""
    return re.sub(r"[^0-9A-Z]", "", str(code or "").upper())


def _range_header(ws, max_scan=40):
    """Başlık satırını (Option Kod + KUMAŞ-MALZEME TİPİ) bulur."""
    for i, row in enumerate(ws.iter_rows(max_row=max_scan, values_only=True)):
        h = [_norm(c) for c in row]
        if _norm("Option Kod") in h and _norm(FIELDS["kumas"][1]) in h:
            return i, h
    return None, None


def is_range_file(path) -> bool:
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        found = any(_range_header(ws)[0] is not None for ws in wb.worksheets)
        wb.close()
        return found
    except Exception:
        return False


def load_range(path) -> dict:
    """RANGE dosyasını okur: {option_key: {kumas, bitim, paca, yaka}}"""
    out = {}
    wb = load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        hi, h = _range_header(ws)
        if hi is None:
            continue
        cols = {k: h.index(_norm(FIELDS[k][1])) if _norm(FIELDS[k][1]) in h else None
                for k in RANGE_KEYS}
        oi = h.index(_norm("Option Kod"))
        for r in ws.iter_rows(min_row=hi + 2, values_only=True):
            key = _opt_key(r[oi] if oi < len(r) else None)
            if not key:
                continue  # pivot ara toplam / boş satır
            out[key] = {k: (str(r[i]).strip() if i is not None and i < len(r)
                            and r[i] not in (None, "") else "")
                        for k, i in cols.items()}
    wb.close()
    return out


def save_range(data: bytes) -> Path:
    RANGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RANGE_FILE.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(RANGE_FILE)
    return RANGE_FILE


def apply_range(items, rng) -> list:
    """Opsiyonlara RANGE bilgilerini ekler; eksikleri döner.
    Döner: [{option_kod, urun_ad, klasman, sorun}] (option başına bir kez)"""
    warnings, seen = [], set()
    for it in items:
        rec = rng.get(_opt_key(it["option_kod"]))
        need = range_required(it["klasman"])
        for k in RANGE_KEYS:
            it[k] = (rec or {}).get(k, "")
        it["range_need"] = need
        if rec is None:
            it["range_eksik"] = need
            sorun = "RANGE dosyasında yok"
        else:
            it["range_eksik"] = [k for k in need if not it[k]]
            sorun = ("Boş: " + ", ".join(FIELDS[k][0] for k in it["range_eksik"])
                     if it["range_eksik"] else "")
        if sorun and it["option_kod"] not in seen:
            seen.add(it["option_kod"])
            warnings.append({"option_kod": it["option_kod"], "urun_ad": it["urun_ad"],
                             "klasman": it["klasman"], "sorun": sorun})
    return warnings


# ── Görseller ────────────────────────────────────────────────────

_http = requests.Session()
_http.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Referer": "https://www.lcw.com/",
})


_CDN = "https://img-lcwaikiki.mncdn.com"
_CDN_RE = re.compile(
    r"https?://img-lcwaikiki\.mncdn\.com/(?:mn\w+/\d+/\d+/(?:[0-9a-fA-F]{6}/)?)?"
    r"(pim/productimages/[^\s\"'<>?]+?\.(?:jpe?g|png|webp))", re.I)


def _hires_candidates(url: str) -> list:
    """Excel'deki küçük (600x800) görsel linkinden yüksek çözünürlüklü
    adayları türetir; en sonda orijinal link denenir."""
    out = []
    m = _CDN_RE.match(url or "")
    if m:
        path = m.group(1)
        out += [f"{_CDN}/mnpadding/1200/1600/ffffff/{path}", f"{_CDN}/{path}"]
    if url and url.startswith("http"):
        out.append(url)
    return list(dict.fromkeys(out))


def search_lcw_image(option_kod: str):
    """lcw.com'da option kod ile arama yapıp ürün görselinin linkini bulur.
    LCW görsel dosya adları option kodu içerir (ör. ..._20262-w6if34z8-cvl_u.jpg)."""
    code = option_kod.lower()
    for url in (f"https://www.lcw.com/arama?q={option_kod}",
                f"https://www.lcw.com/arama?q={option_kod.split('-')[0]}"):
        try:
            r = _http.get(url, timeout=20)
            if r.status_code != 200:
                continue
        except Exception as e:
            log.debug(f"lcw.com araması başarısız {option_kod}: {e}")
            return None
        html = r.text.replace("\\/", "/")
        paths = [m.group(1) for m in _CDN_RE.finditer(html)]
        hit = [p for p in paths if code in p.lower()]
        if hit:
            # Ön görünüm (_a) varsa onu tercih et
            hit.sort(key=lambda p: 0 if re.search(r"_a\.\w+$", p) else 1)
            return f"{_CDN}/{hit[0]}"
    return None


def _download(url: str, size):
    r = _http.get(url, timeout=25)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    if im.width < 200:
        raise ValueError("görsel çok küçük")
    im.thumbnail(size)
    return im


def _fetch_image(url: str, option_kod: str = "", size=(600, 800)):
    """Ürün görselini en yüksek çözünürlükle indirir, diske cache'ler.
    Excel linki çalışmazsa lcw.com'da option kod ile arar. Hata → None."""
    key = hashlib.sha1(f"{url}|{option_kod}|{size}".encode()).hexdigest()
    path = IMG_CACHE_DIR / (key + ".jpg")
    if path.exists():
        return str(path)
    im = None
    for cand in _hires_candidates(url):
        try:
            im = _download(cand, size)
            break
        except Exception as e:
            log.debug(f"Görsel indirilemedi {cand}: {e}")
    if im is None and option_kod:
        found = search_lcw_image(option_kod)
        for cand in _hires_candidates(found):
            try:
                im = _download(cand, size)
                break
            except Exception as e:
                log.debug(f"Görsel indirilemedi {cand}: {e}")
    if im is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    im.save(tmp, "JPEG", quality=85, optimize=True)
    tmp.replace(path)
    return str(path)


def fetch_images(items, workers=12, progress=None, size=(600, 800)) -> int:
    keys = list(dict.fromkeys((it["resim"], it["option_kod"]) for it in items))
    done = ok = 0
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, p in zip(keys, ex.map(lambda k: _fetch_image(k[0], k[1], size), keys)):
            results[k] = p
            done += 1
            ok += bool(p)
            if progress and done % 25 == 0:
                progress(f"Görseller: {done}/{len(keys)}")
    for it in items:
        it["img_path"] = results.get((it["resim"], it["option_kod"]))
        # Kartta tıklanınca açılacak link: Excel'deki link yoksa lcw.com araması
        if not it["resim"].startswith("http"):
            it["resim"] = f"https://www.lcw.com/arama?q={it['option_kod']}"
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
    WARN_ROWS = 30  # uyarı sayfası başına satır

    def __init__(self, items, hidden, title, subtitle, out_path, big=False, warnings=None):
        self.items = items
        self.hidden = set(hidden)
        self.title = title
        self.subtitle = subtitle
        self.out_path = out_path
        self.warnings = [] if "uyari" in self.hidden else (warnings or [])
        # En başta uyarı sayfası(ları), sonra kapak
        self.warn_pages = -(-len(self.warnings) // self.WARN_ROWS)
        self.pre = self.warn_pages + 1
        self.font, self.bold = _register_fonts()
        self.show_img = "resim" not in self.hidden
        self.big = big and self.show_img
        if self.big:
            # Detaylı görsel: sayfada 4 büyük kart
            self.cols = 4
        else:
            self.cols = COLS if self.show_img else COLS - 1
        self.card_w = (PAGE_W - 2 * MARGIN - (self.cols - 1) * GAP) / self.cols
        if not self.show_img:
            self.img_h = 0
        elif self.big:
            self.img_h = (self.card_w - 8) * 4 / 3
        else:
            # Sayfaya 2 kart satırı + 2 grup başlığı sığacak yükseklik
            self.img_h = 126
        # RANGE bilgisi varsa kartta Kumaş / Bitim / Paça-Yaka satırları
        self.has_range = any("range_need" in it for it in items)
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
        if "cluster" not in self.hidden:
            lines.append(("kv", it and ("Cluster", it["cluster"] or "-")))
        if self.has_range:
            # Kumaş, Bitim İşlemi + klasmana göre Paça Detayı ya da Yaka Tipi
            # (kart yüksekliği sabit kalsın diye son satır hep ayrılır)
            for slot in ("kumas", "bitim", "detay"):
                if slot == "detay":
                    keys = [k for k in ("paca", "yaka")
                            if k not in self.hidden and (it is None or k in it["range_need"])]
                    if it is None:
                        if keys:
                            lines.append(("kv", None))
                        continue
                    if not keys:
                        if any(k not in self.hidden for k in ("paca", "yaka")):
                            lines.append(("kv", ("", "")))
                        continue
                    key = keys[0]
                elif slot in self.hidden:
                    continue
                else:
                    key = slot
                if it is None:
                    lines.append(("kv", None))
                elif key in it["range_eksik"]:
                    lines.append(("kvr", (FIELDS[key][0], "EKSİK")))
                else:
                    lines.append(("kv", (FIELDS[key][0], it[key] or "-")))
        return lines

    # ── Sayfalama ────────────────────────────────────────────────
    def _paginate(self):
        """Blokları sayfalara yerleştirir.
        Döner: pages = [[(tip, veri, y), ...], ...], toc = [(grup, alt, sayfa)]"""
        def sort_key(it):
            return (tuple(it[k] for k in self.group_keys),
                    -(it["stok"] or 0))  # grup içinde stok adedi büyükten küçüğe
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
            toc.append((gkey, len(gitems), len(pages) + 1 + self.pre))
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
        c.drawString(MARGIN, MARGIN - 6,
                     self._fit(c, self.subtitle, self.font, 7.5, PAGE_W - 2 * MARGIN - 70))
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
                c.setFillColor(C_ACCENT if kind == "kvr" else C_TEXT)
                c.drawRightString(tx + tw_, cy,
                                  self._fit(c, v, self.bold, 8, tw_ * 0.55))
            cy -= 10.5

    def _draw_warnings(self, c, total):
        """RANGE'de eksik olan opsiyonlar: kırmızı uyarı sayfası."""
        rows = self.warnings
        for pno in range(self.warn_pages):
            chunk = rows[pno * self.WARN_ROWS:(pno + 1) * self.WARN_ROWS]
            self._header(c, pno + 1, total, "RANGE kontrol uyarısı")
            y = PAGE_H - 62
            c.setFillColor(C_ACCENT)
            c.roundRect(MARGIN, y - 34, PAGE_W - 2 * MARGIN, 34, 4, stroke=0, fill=1)
            c.setFillColor(HexColor("#ffffff"))
            c.setFont(self.bold, 13)
            c.drawString(MARGIN + 12, y - 15,
                         f"⚠ UYARI: {len(rows)} opsiyonda RANGE bilgisi eksik")
            c.setFont(self.font, 8.5)
            c.drawString(MARGIN + 12, y - 28,
                         "Kumaş / Bitim İşlemi (tümü), Paça Detayı (pantolon), "
                         "Yaka Tipi (hırka) RANGE kontrol dosyasında doldurulmalı.")
            y -= 52
            cols = [(MARGIN, "Option Kod"), (MARGIN + 110, "Ürün Ad"),
                    (MARGIN + 290, "Klasman"), (MARGIN + 500, "Sorun")]
            c.setFont(self.bold, 8.5)
            c.setFillColor(C_MUTED)
            for x, lab in cols:
                c.drawString(x, y, lab)
            y -= 4
            c.setStrokeColor(C_LINE)
            c.line(MARGIN, y, PAGE_W - MARGIN, y)
            for w in chunk:
                y -= 13.5
                c.setFont(self.bold, 8.5)
                c.setFillColor(C_BRAND)
                c.drawString(cols[0][0], y, w["option_kod"])
                c.setFont(self.font, 8.5)
                c.setFillColor(C_TEXT)
                c.drawString(cols[1][0], y, self._fit(c, w["urun_ad"], self.font, 8.5, 175))
                c.drawString(cols[2][0], y, self._fit(c, w["klasman"], self.font, 8.5, 205))
                c.setFillColor(C_ACCENT)
                c.drawString(cols[3][0], y, self._fit(c, w["sorun"], self.font, 8.5,
                                                      PAGE_W - MARGIN - cols[3][0]))
            c.bookmarkPage(f"w{pno}")
            if pno == 0:
                c.addOutlineEntry("⚠ RANGE uyarısı", "w0", level=0)
            c.showPage()

    def _draw_cover(self, c, toc, total):
        self._header(c, self.pre, total, datetime.now().strftime("%d.%m.%Y"))
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

        if self.warnings:
            c.setFillColor(C_ACCENT)
            c.setFont(self.bold, 9.5)
            c.drawString(MARGIN, PAGE_H - 184,
                         f"⚠ {len(self.warnings)} opsiyonda RANGE bilgisi eksik — "
                         f"ilk sayfadaki listeye bakın.")

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
        total = len(pages) + self.pre
        c = canvas.Canvas(str(self.out_path), pagesize=(PAGE_W, PAGE_H))
        c.setTitle(self.title)
        c.setAuthor("Burç Agent · Merch Raporu")
        self._draw_warnings(c, total)
        self._draw_cover(c, toc, total)
        c.bookmarkPage(f"p{self.pre}")
        c.addOutlineEntry("Kapak / İçindekiler", f"p{self.pre}", level=0)
        c.showPage()
        last_main = None
        for pi, page in enumerate(pages, start=self.pre + 1):
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


# ── HTML rapor (görseller açılırken tarayıcıda yüklenir) ─────────

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --brand:#002f6c; --accent:#e30613; --text:#1d2433; --muted:#6b7385;
          --line:#d9dee8; --soft:#f3f5f9; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font:13px/1.4 -apple-system,"Segoe UI",Roboto,Arial,sans-serif; color:var(--text); background:#fff; }
  header { background:var(--brand); color:#fff; padding:14px 20px; border-bottom:3px solid var(--accent); }
  header h1 { font-size:20px; }
  header p { font-size:12px; color:#cfd8ea; margin-top:2px; }
  .bar { position:sticky; top:0; z-index:5; background:#fff; border-bottom:1px solid var(--line);
         padding:10px 20px; display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center; }
  .bar b { font-size:12px; color:var(--muted); font-weight:600; }
  .chk { display:flex; flex-wrap:wrap; gap:4px 12px; flex:1; }
  .chk i { color:var(--line); font-style:normal; }
  .bar .break { flex-basis:100%; height:0; }
  .bar label { font-size:12px; display:flex; gap:4px; align-items:center; cursor:pointer; }
  .bar button { margin-left:auto; background:var(--brand); color:#fff; border:0; border-radius:6px;
                padding:8px 14px; font-weight:600; cursor:pointer; }
  .stats { display:flex; flex-wrap:wrap; gap:10px; padding:16px 20px 4px; }
  .stat { background:var(--soft); border-left:4px solid var(--brand); border-radius:6px; padding:8px 14px; min-width:130px; }
  .stat b { font-size:20px; display:block; }
  .stat span { font-size:11px; color:var(--muted); }
  main { padding:8px 20px 30px; }
  h2 { font-size:16px; color:#fff; background:var(--brand); padding:8px 12px; border-radius:6px; margin:22px 0 8px; }
  h3 { font-size:13px; color:var(--brand); background:var(--soft); border-left:4px solid var(--accent);
       padding:7px 10px; border-radius:4px; margin:14px 0 8px; display:flex; justify-content:space-between; }
  h3 small { color:var(--muted); font-weight:400; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; }
  .card { border:1px solid var(--line); border-radius:8px; overflow:hidden; break-inside:avoid; page-break-inside:avoid; background:#fff;
          content-visibility:auto; contain-intrinsic-size:auto 440px; }
  .dd { position:relative; font-size:12px; }
  .dd summary { cursor:pointer; padding:2px 8px; border:1px solid var(--line); border-radius:6px; }
  .dd .ddl { position:absolute; z-index:10; background:#fff; border:1px solid var(--line); border-radius:8px;
             box-shadow:0 6px 18px rgba(0,0,0,.12); padding:8px 10px; max-height:340px; overflow:auto;
             min-width:280px; display:flex; flex-direction:column; gap:3px; }
  .dd .dds { padding:5px 8px; border:1px solid var(--line); border-radius:6px; font:inherit; margin-bottom:4px; }
  .dd label[hidden] { display:none; }
  .dd .none { color:var(--muted); }
  .img { position:relative; aspect-ratio:3/4; background:var(--soft); display:block; }
  .img img { width:100%; height:100%; object-fit:contain; display:block; }
  .img .ph { position:absolute; inset:0; display:none; align-items:center; justify-content:center;
             text-align:center; color:var(--muted); font-size:12px; padding:10px; }
  .img.err img { display:none; } .img.err .ph { display:flex; }
  .badge { position:absolute; top:6px; right:6px; color:#fff; font-size:10px; font-weight:700;
           border-radius:10px; padding:2px 8px; }
  .body { padding:7px 9px 9px; }
  .code { font-weight:700; color:var(--brand); text-decoration:none; }
  .zoom { float:right; text-decoration:none; font-size:12px; }
  @media print { .zoom { display:none; } }
  .name { font-size:12px; } .color { font-size:11px; color:var(--muted); }
  .kv { display:flex; justify-content:space-between; font-size:11px; color:var(--muted); }
  .kv b { color:var(--text); }
  .noimg .img { display:none; }
  .kv.miss b { color:var(--accent); }
  [hidden] { display:none !important; }
  .tabs { display:flex; gap:6px; padding:12px 20px 0; }
  .tabs button { background:#fff; color:var(--brand); border:1px solid var(--line); border-radius:7px 7px 0 0;
                 padding:7px 18px; font-weight:600; cursor:pointer; font-size:13px; }
  .tabs button.on { background:var(--brand); color:#fff; border-color:var(--brand); }
  #ozet { padding:0 20px 30px; }
  #ozet .stats { padding-left:0; padding-right:0; }
  #ozet .note { font-size:12px; color:var(--muted); margin:4px 0 6px; }
  .tblw { overflow-x:auto; }
  table.sum { border-collapse:collapse; width:100%; font-size:12px; }
  table.sum th { background:var(--brand); color:#fff; font-weight:600; padding:7px 8px; text-align:left; position:sticky; top:0; }
  table.sum td { padding:5px 8px; border-bottom:1px solid var(--line); }
  table.sum .num { text-align:right; white-space:nowrap; }
  table.sum td.num small { display:block; color:var(--muted); font-size:10px; }
  table.sum td.ex { color:var(--muted); font-size:11px; }
  table.sum td.good { color:var(--ok, #0f7b3f); }
  table.sum tr.tot td { background:var(--soft); font-weight:700; border-top:2px solid var(--brand); }
  table.sum .z { color:var(--line); }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:4px; vertical-align:middle; }
  .warn { margin:16px 20px 0; border:2px solid var(--accent); border-radius:8px; overflow:hidden; }
  .warn h4 { background:var(--accent); color:#fff; padding:9px 12px; font-size:15px;
             display:flex; justify-content:space-between; align-items:center; }
  .warn h4 button { background:#fff; color:var(--accent); border:0; border-radius:5px;
                    padding:3px 10px; font-weight:700; cursor:pointer; font-size:12px; }
  .warn .more { padding:6px 12px 10px; }
  .warn .more button { background:#fff; color:var(--accent); border:1px solid var(--accent); border-radius:5px;
                       padding:4px 12px; font-weight:600; cursor:pointer; }
  @media print { .warn h4 button, .warn .more { display:none; } }
  .warn p { padding:6px 12px 0; font-size:12px; color:var(--muted); }
  .warn table { width:100%; border-collapse:collapse; font-size:12px; margin:6px 0 4px; }
  .warn th, .warn td { text-align:left; padding:4px 12px; border-bottom:1px solid var(--line); }
  .warn td.s { color:var(--accent); font-weight:600; }
  .warn th { color:var(--muted); font-weight:500; }
  .noimg .badge { position:static; display:inline-block; margin-bottom:3px; }
  @media print {
    @page { size:A4 landscape; margin:9mm; }
    .bar, .tabs { display:none; }
    table.sum th, table.sum td, .dot { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    .card { content-visibility:visible; }
    header { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    h2, h3, .badge, .stat { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    .grid { grid-template-columns:repeat(5,1fr); gap:6px; }
    h2 { break-before:page; } h2.first { break-before:auto; }
    h3 { break-after:avoid; }
    body { font-size:11px; }
  }
</style>
</head>
<body>
<header><h1>__TITLE__</h1><p>__SUBTITLE__</p></header>
<div class="bar" id="bar">
  <b>Filtre:</b>
  <span id="filters" class="chk"></span>
  <button onclick="window.print()">PDF olarak kaydet / Yazdır</button>
  <span class="break"></span>
  <b>Gizle:</b>
  <span id="toggles" class="chk"></span>
</div>
<nav class="tabs" id="tabs"><button type="button" data-v="urun" class="on">Ürünler</button><button type="button" data-v="ozet">Özet</button></nav>
<div id="warn"></div>
<div class="stats" id="stats"></div>
<main id="main"></main>
<section id="ozet" hidden></section>
<script>
const DATA = __DATA__;
const FIELDS = __FIELDS__;
const HIDDEN = new Set(__HIDDEN__);
const DURUM_COLORS = __COLORS__;
const DURUM_ORDER = __ORDER__;
// Kumaş / Ana Kumaş sadece Excel'de varsa gösterilir
const WARNINGS = __WARNINGS__;
// RANGE dosyası yüklüyse Kumaş / Bitim İşlemi / Paça Detayı / Yaka Tipi gösterilir
const HAS_RANGE = DATA.some(i => i.range_need);
const RANGE_KEYS = ['kumas', 'bitim', 'paca', 'yaka'];
// Sayfa içi filtreler: işaretli olmayan değerler gizlenir
const FILTERS = {
  buyer: ['Buyer Grup', [...new Set(DATA.map(i => i.buyer || '-'))].sort((a, b) => a.localeCompare(b, 'tr'))],
  merch_alt_grup: ['Merch Alt Grup', [...new Set(DATA.map(i => i.merch_alt_grup || '-'))].sort()],
  klasman: ['Klasman', [...new Set(DATA.map(i => i.klasman || '-'))].sort((a, b) => a.localeCompare(b, 'tr'))],
  cluster: ['Cluster', [...new Set(DATA.map(i => i.cluster || '-'))].sort()],
  durum: ['Durum', [...new Set(DATA.map(i => i.durum))].sort((a, b) => (DURUM_ORDER[a] ?? 99) - (DURUM_ORDER[b] ?? 99))],
};
// Açılışta seçili gelenler; değerlerin hiçbiri veride yoksa o grup "Tümü"
const DEFAULT_ON = __DEFAULT_ON__;
const OFF = {};
const normV = v => String(v ?? '').trim().toLocaleLowerCase('tr');
// Arama: Türkçe harf/aksan duyarsız ("hirka" → "HIRKA")
const fold = v => normV(v).normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/ı/g, 'i');
for (const [k, [, vals]] of Object.entries(FILTERS)) {
  const want = new Set((DEFAULT_ON[k] || []).map(normV));
  const hit = vals.filter(v => want.has(normV(v)));
  OFF[k] = new Set(hit.length ? vals.filter(v => !want.has(normV(v))) : []);
}
const fmt = (v, d) => v == null ? '-' : v.toLocaleString('tr-TR', {minimumFractionDigits: d, maximumFractionDigits: d});
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const search = code => 'https://www.lcw.com/arama?q=' + encodeURIComponent(code);

// Kartta Excel'deki 600x800 görsel (hızlı), olmazsa diğer boyutlar; 🔍 yüksek çözünürlük
const CDN = 'https://img-lcwaikiki.mncdn.com';
const CDN_RE = /^https?:\/\/img-lcwaikiki\.mncdn\.com\/(?:mn\w+\/\d+\/\d+\/(?:[0-9a-fA-F]{6}\/)?)?(pim\/productimages\/[^\s"'<>?]+?\.(?:jpe?g|png|webp))/i;
function imgUrls(u) {
  if (!u || !u.startsWith('http')) return {card: [], big: ''};
  const m = CDN_RE.exec(u);
  if (!m) return {card: [u], big: u};
  const big = `${CDN}/mnpadding/1200/1600/ffffff/${m[1]}`;
  return {card: [...new Set([u, `${CDN}/mnpadding/600/800/ffffff/${m[1]}`, big, `${CDN}/${m[1]}`])], big};
}
// Görsel sırayla denenir; hepsi başarısızsa "lcw.com'da ara" gösterilir
function imgFail(el) {
  const urls = JSON.parse(el.dataset.urls);
  const i = +(el.dataset.i || 0) + 1;
  if (i < urls.length) { el.dataset.i = i; el.src = urls[i]; }
  else el.parentNode.classList.add('err');
}

const LABELS = Object.fromEntries(FIELDS);
function rangeLines(it) {
  // Kumaş ve Bitim İşlemi her üründe; Paça Detayı pantolonda, Yaka Tipi hırkada
  return RANGE_KEYS.filter(k => (k === 'kumas' || k === 'bitim' || (it.range_need || []).includes(k)) && !HIDDEN.has(k))
    .map(k => (it.range_eksik || []).includes(k)
      ? `<div class="kv miss"><span>${LABELS[k]}</span><b>EKSİK</b></div>`
      : `<div class="kv"><span>${LABELS[k]}</span><b>${esc(it[k] || '-')}</b></div>`).join('');
}

function card(it) {
  const h = HIDDEN;
  const col = DURUM_COLORS[it.durum] || '#555';
  const badge = h.has('durum') ? '' : `<span class="badge" style="background:${col}">${esc(it.durum)}</span>`;
  // Görsele tıklayınca lcw.com'da ürün aranır (kumaş vb. detaylar ürün sayfasında)
  const link = search(it.option_kod);
  const u = imgUrls(it.img);
  const img = h.has('resim') ? '' : `<a class="img${u.card.length ? '' : ' err'}" href="${esc(link)}" target="_blank" rel="noopener">
      ${u.card.length ? `<img loading="lazy" decoding="async" src="${esc(u.card[0])}" data-urls='${esc(JSON.stringify(u.card))}' onerror="imgFail(this)" alt="${esc(it.option_kod)}">` : ''}
      <span class="ph">Görsel yüklenemedi<br>lcw.com'da açmak için tıklayın</span>${badge}</a>`;
  const kv = (k, label, v) => h.has(k) ? '' : `<div class="kv"><span>${label}</span><b>${v}</b></div>`;
  return `<div class="card">${img}<div class="body">
    ${h.has('resim') ? badge : ''}
    ${h.has('option_kod') ? '' : `<a class="code" href="${esc(search(it.option_kod))}" target="_blank" rel="noopener" title="lcw.com'da aç">${esc(it.option_kod)}</a>`}
    ${u.big ? `<a class="zoom" href="${esc(u.big)}" target="_blank" rel="noopener" title="Görseli büyük aç">🔍</a>` : ''}
    ${h.has('urun_ad') ? '' : `<div class="name">${esc(it.urun_ad)}</div>`}
    ${h.has('renk') ? '' : `<div class="color">${esc(it.renk)}</div>`}
    ${kv('stok', 'Gün Sonu Reyon Stok Ort.', fmt(it.stok, 0))}
    ${kv('satis', 'Satış Adet', fmt(it.satis, 0))}
    ${kv('devir', 'Devir Hızı', fmt(it.devir, 2))}
    ${kv('cluster', 'Cluster', esc(it.cluster || '-'))}
    ${HAS_RANGE ? rangeLines(it) : ''}
  </div></div>`;
}

// Sekmeler: Ürünler (kartlar) / Özet (Buyer Grup ve Klasman × Durum tabloları)
let VIEW = 'urun';
document.getElementById('tabs').addEventListener('click', e => {
  const v = e.target.dataset.v;
  if (!v || v === VIEW) return;
  VIEW = v;
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
  render();
});

function render() {
  const ozet = VIEW === 'ozet';
  ['warn', 'stats', 'main'].forEach(id => document.getElementById(id).hidden = ozet);
  document.getElementById('ozet').hidden = !ozet;
  if (ozet) { renderSummary(); return; }
  document.body.classList.toggle('noimg', HIDDEN.has('resim'));
  document.getElementById('warn').style.display = HIDDEN.has('uyari') ? 'none' : '';
  const keys = ['merch_alt_grup', 'klasman'].filter(k => !HIDDEN.has(k));
  const shown = DATA.filter(i => Object.keys(FILTERS).every(k => !OFF[k].has(i[k] || '-')));
  renderStats(shown);
  renderWarn(shown);
  const items = shown.sort((a, b) =>
    keys.map(k => a[k].localeCompare(b[k], 'tr')).find(x => x) ||
    (b.stok || 0) - (a.stok || 0));  // grup içinde stok adedi büyükten küçüğe
  let html = '', main = null, sub = null, buf = [];
  const flush = () => {
    if (!buf.length) return;
    if (keys.includes('klasman')) {
      const cnt = {}; buf.forEach(i => cnt[i.durum] = (cnt[i.durum] || 0) + 1);
      html += `<h3>${esc(sub)} <small>${buf.length} opsiyon · ${Object.entries(cnt).map(([d, n]) => `${esc(d)}: ${n}`).join(' · ')}</small></h3>`;
    }
    html += `<div class="grid">${buf.map(card).join('')}</div>`; buf = [];
  };
  let first = true;
  for (const it of items) {
    if (keys.includes('merch_alt_grup') && it.merch_alt_grup !== main) {
      flush(); main = it.merch_alt_grup; sub = null;
      html += `<h2 class="${first ? 'first' : ''}">${esc(main)}</h2>`; first = false;
    }
    if (keys.includes('klasman') && it.klasman !== sub) { flush(); sub = it.klasman; }
    buf.push(it);
  }
  flush();
  document.getElementById('main').innerHTML = html;
}

// ── Özet: Durum filtresi hariç diğer filtrelere uyan satırlar; durumlar sütunlarda ──
const pct = (n, t) => t ? (n / t * 100).toLocaleString('tr-TR', {maximumFractionDigits: 1}) + '%' : '-';
function summaryTable(base, key, title, extra) {
  const durums = FILTERS.durum[1];
  const groups = new Map();
  for (const i of base) {
    const g = i[key] || '-';
    if (!groups.has(g)) groups.set(g, {n: 0, d: {}, ex: new Set()});
    const r = groups.get(g);
    r.n++; r.d[i.durum] = (r.d[i.durum] || 0) + 1;
    if (extra) r.ex.add(i[extra[0]] || '-');
  }
  const rows = [...groups.entries()].sort((a, b) => b[1].n - a[1].n);
  const tot = {n: base.length, d: {}};
  base.forEach(i => tot.d[i.durum] = (tot.d[i.durum] || 0) + 1);
  const good = r => (r.d['Çok İyi'] || 0) + (r.d['İyi'] || 0);
  const cell = (r, d) => {
    const n = r.d[d] || 0, p = r.n ? n / r.n : 0;
    const bg = n ? `background:${DURUM_COLORS[d] || '#7a7f8c'}${Math.round(18 + p * 150).toString(16).padStart(2, '0')}` : '';
    return `<td class="num" style="${bg}">${n ? `<b>${n}</b><small>${pct(n, r.n)}</small>` : '<span class="z">–</span>'}</td>`;
  };
  const line = (name, r, cls = '') => `<tr class="${cls}"><td class="g">${esc(name)}</td>` +
    (extra ? `<td class="ex">${esc([...(r.ex || [])].sort().join(', '))}</td>` : '') +
    `<td class="num"><b>${r.n}</b></td>${durums.map(d => cell(r, d)).join('')}<td class="num good"><b>${pct(good(r), r.n)}</b></td></tr>`;
  return `<h3>${esc(title)} <small>${rows.length} satır</small></h3><div class="tblw"><table class="sum"><thead><tr><th>${esc(FILTERS[key][0])}</th>` +
    (extra ? `<th>${esc(extra[1])}</th>` : '') + `<th class="num">Option Adet</th>` +
    durums.map(d => `<th class="num"><span class="dot" style="background:${DURUM_COLORS[d] || '#7a7f8c'}"></span>${esc(d)}</th>`).join('') +
    `<th class="num">Çok İyi + İyi Oranı</th></tr></thead><tbody>` +
    rows.map(([g, r]) => line(g, r)).join('') + line('Toplam', tot, 'tot') + '</tbody></table></div>';
}
function renderSummary() {
  const base = DATA.filter(i => Object.keys(FILTERS).every(k => k === 'durum' || !OFF[k].has(i[k] || '-')));
  const good = base.filter(i => i.durum === 'Çok İyi' || i.durum === 'İyi').length;
  document.getElementById('ozet').innerHTML =
    `<div class="stats"><div class="stat"><b>${base.length}</b><span>Option Adet</span></div>
      <div class="stat" style="border-color:${DURUM_COLORS['Çok İyi']}"><b>${good}</b><span>Çok İyi + İyi</span></div>
      <div class="stat" style="border-color:${DURUM_COLORS['İyi']}"><b>${pct(good, base.length)}</b><span>Çok İyi + İyi Oranı</span></div></div>
     <p class="note">Buyer Grup / Merch Alt Grup / Klasman / Cluster filtrelerine göre hesaplanır; Durum filtresi bu sayfada uygulanmaz (tüm durumlar sütunlarda).
      Oranlar satır toplamına göredir. G ve K birlikte seçiliyse bir option her cluster için ayrı sayılır.</p>` +
    summaryTable(base, 'buyer', 'Buyer Grup › Durum') +
    summaryTable(base, 'klasman', 'Klasman › Durum', ['buyer', 'Buyer Grup']);
}

function renderStats(rows) {
  const cnt = {}; rows.forEach(i => cnt[i.durum] = (cnt[i.durum] || 0) + 1);
  document.getElementById('stats').innerHTML =
    `<div class="stat"><b>${rows.length}</b><span>Toplam Opsiyon</span></div>` +
    Object.entries(cnt).sort((a, b) => (DURUM_ORDER[a[0]] ?? 99) - (DURUM_ORDER[b[0]] ?? 99)).map(([d, n]) =>
      `<div class="stat" style="border-color:${DURUM_COLORS[d] || '#555'}"><b>${n}</b><span>${esc(d)}</span></div>`).join('') +
    `<div class="stat"><b>${fmt(rows.reduce((s, i) => s + (i.satis || 0), 0), 0)}</b><span>Toplam Satış Adet</span></div>`;
}
// Her grubun başında "Tümü". Çok değerli gruplar açılır listede ve aranabilir.
// Klasman listesinde sadece seçili Buyer Grup + Merch Alt Grup'ta olan klasmanlar görünür.
function availKlasman() {
  const av = new Set();
  for (const i of DATA)
    if (!OFF.buyer.has(i.buyer || '-') && !OFF.merch_alt_grup.has(i.merch_alt_grup || '-')) av.add(i.klasman || '-');
  return av;
}
function ddLabel(k) {
  const vals = k === 'klasman' ? [...availKlasman()] : FILTERS[k][1];
  return `${FILTERS[k][0]} (${vals.filter(v => !OFF[k].has(v)).length}/${vals.length})`;
}
document.getElementById('filters').innerHTML = Object.entries(FILTERS).map(([k, [label, vals]]) => {
  const boxes = `<label class="all"><input type="checkbox" data-all="${k}" ${OFF[k].size ? '' : 'checked'}><b>Tümü</b></label>` + vals.map(v =>
    `<label data-t="${esc(fold(v))}"><input type="checkbox" data-f="${k}" value="${esc(v)}" ${OFF[k].has(v) ? '' : 'checked'}>${esc(v)}</label>`).join('');
  return vals.length > 8
    ? `<details class="dd"><summary id="dd-${k}">${esc(ddLabel(k))}</summary><div class="ddl" id="ddl-${k}">
         <input type="search" class="dds" data-s="${k}" placeholder="Ara…">${boxes}<span class="none" hidden>Eşleşen yok</span></div></details>`
    : `<span>${esc(label)}:</span>${boxes}`;
}).join('<i>|</i>');

// Açılır listede arama + klasman daraltma
function refreshList(k) {
  const box = document.getElementById('ddl-' + k);
  if (!box) return;
  const q = fold(box.querySelector('.dds').value);
  const av = k === 'klasman' ? availKlasman() : null;
  let n = 0;
  box.querySelectorAll('label[data-t]').forEach(l => {
    const v = l.querySelector('input').value;
    const ok = (!av || av.has(v)) && (!q || l.dataset.t.includes(q));
    l.hidden = !ok; n += ok;
  });
  box.querySelector('.none').hidden = n > 0;
  const allCb = box.querySelector('input[data-all]');
  const vis = [...box.querySelectorAll('label[data-t]')].filter(l => !l.hidden);
  allCb.checked = vis.length > 0 && vis.every(l => l.querySelector('input').checked);
  document.getElementById('dd-' + k).textContent = ddLabel(k);
}
document.getElementById('filters').addEventListener('input', e => {
  if (e.target.dataset.s) refreshList(e.target.dataset.s);
});
document.getElementById('filters').addEventListener('change', e => {
  const {f, all} = e.target.dataset;
  const k = all || f;
  if (!k) return;
  const box = document.getElementById('filters');
  if (all) {
    // "Tümü" o an görünen (aramaya/daraltmaya uyan) değerlere uygulanır
    box.querySelectorAll(`input[data-f="${all}"]`).forEach(cb => {
      if (cb.closest('label').hidden) return;
      cb.checked = e.target.checked;
      e.target.checked ? OFF[all].delete(cb.value) : OFF[all].add(cb.value);
    });
  } else {
    e.target.checked ? OFF[f].delete(e.target.value) : OFF[f].add(e.target.value);
    const allCb = box.querySelector(`input[data-all="${f}"]`);
    if (!document.getElementById('ddl-' + f)) allCb.checked = OFF[f].size === 0;
  }
  refreshList(k);
  if (k === 'buyer' || k === 'merch_alt_grup') refreshList('klasman');
  render();
});
document.querySelectorAll('.ddl').forEach(b => refreshList(b.id.slice(4)));
// Uyarı listesi sadece filtrede görünen opsiyonları kapsar; ilk 10 satır, gerisi "Tümünü göster"
let warnAll = false;
function renderWarn(shown) {
  const codes = new Set(shown.map(i => i.option_kod));
  const ws = WARNINGS.filter(w => codes.has(w.option_kod));
  const el = document.getElementById('warn');
  if (!ws.length) { el.innerHTML = ''; return; }
  const rows = warnAll ? ws : ws.slice(0, 10);
  el.innerHTML =
    `<div class="warn"><h4><span>⚠ UYARI: ${ws.length} opsiyonda RANGE bilgisi eksik</span>
     <button type="button" onclick="hideWarn()">✕ Gizle</button></h4>
     <p>Kumaş ve Bitim İşlemi tüm ürünlerde, Paça Detayı pantolonlarda, Yaka Tipi hırkalarda RANGE kontrol dosyasında doldurulmalı.</p>
     <table><tr><th>Option Kod</th><th>Ürün Ad</th><th>Klasman</th><th>Sorun</th></tr>` +
    rows.map(w => `<tr><td><b>${esc(w.option_kod)}</b></td><td>${esc(w.urun_ad)}</td><td>${esc(w.klasman)}</td><td class="s">${esc(w.sorun)}</td></tr>`).join('') +
    '</table>' + (ws.length > 10 ? `<p class="more"><button type="button" onclick="warnAll=!warnAll;render()">${
      warnAll ? 'İlk 10 satırı göster' : `Tümünü göster (${ws.length})`}</button></p>` : '') + '</div>';
}
function hideWarn() {
  HIDDEN.add('uyari');
  const cb = document.querySelector('#toggles input[value=uyari]');
  if (cb) cb.checked = true;
  render();
}
document.getElementById('toggles').innerHTML = (WARNINGS.length ? [['uyari', 'RANGE Uyarıları']] : [])
  .concat(FIELDS.filter(([k]) => HAS_RANGE || !RANGE_KEYS.includes(k))).map(([k, label]) =>
  `<label><input type="checkbox" value="${k}" ${HIDDEN.has(k) ? 'checked' : ''}>${esc(label)}</label>`).join('');
document.getElementById('toggles').addEventListener('change', e => {
  e.target.checked ? HIDDEN.add(e.target.value) : HIDDEN.delete(e.target.value); render();
});
render();
</script>
</body>
</html>
"""


def render_html(items, hidden, title, subtitle, out_path, warnings=None, varsayilan=None):
    """Tek dosyalık HTML rapor. Görseller açan kişinin tarayıcısında
    lcw.com sunucusundan yüklenir; önce yüksek çözünürlük, olmazsa
    Excel'deki link, o da olmazsa lcw.com araması gösterilir."""
    data = []
    for it in items:
        d = {k: it.get(k) for k in ("option_kod", "urun_ad", "renk", "durum", "stok",
                                     "satis", "devir", "cluster", "kumas", "bitim",
                                     "paca", "yaka", "range_need", "range_eksik",
                                     "merch_alt_grup", "klasman", "buyer")}
        d["img"] = it["resim"]
        # Boş alanları yazma: binlerce satırda dosyayı belirgin küçültür
        data.append({k: v for k, v in d.items() if v not in (None, "", [])})

    def js(v):
        return json.dumps(v, ensure_ascii=False).replace("</", "<\\/")

    from html import escape
    html = (_HTML_TEMPLATE
            .replace("__TITLE__", escape(title))
            .replace("__SUBTITLE__", escape(subtitle))
            .replace("__DATA__", js(data))
            .replace("__FIELDS__", js([[k, v[0]] for k, v in FIELDS.items()]))
            .replace("__HIDDEN__", js(list(hidden)))
            .replace("__WARNINGS__", js(warnings or []))
            .replace("__DEFAULT_ON__", js(varsayilan or {}))
            .replace("__COLORS__", js(DURUM_COLORS))
            .replace("__ORDER__", js(DURUM_ORDER)))
    Path(out_path).write_text(html, encoding="utf-8")
    return Path(out_path)


# ── Dış API ──────────────────────────────────────────────────────

def build_report(xlsx_path, source_name=None, durumlar=None, gizli_alanlar=None,
                 buyer_gruplar=None, buyuk_gorsel=None, klasman_kelimeler=None,
                 clusterlar=None, range_path=None,
                 out_path=None, download_images=True, progress=None):
    """Excel'den PDF üretir. Ayar verilmezse kayıtlı ayarlar kullanılır.

    Döner: (pdf_path: Path, summary: dict)
    """
    xlsx_path = Path(xlsx_path)
    source_name = source_name or xlsx_path.name
    s = load_settings()
    durumlar = durumlar if durumlar is not None else s["durumlar"]
    gizli = gizli_alanlar if gizli_alanlar is not None else s["gizli_alanlar"]
    buyer = buyer_gruplar if buyer_gruplar is not None else s["buyer_gruplar"]
    klasman_w = (klasman_kelimeler if klasman_kelimeler is not None
                 else s.get("klasman_kelimeler", []))
    cluster_f = clusterlar if clusterlar is not None else s.get("clusterlar", [])
    big = buyuk_gorsel if buyuk_gorsel is not None else s["buyuk_gorsel"]
    if not durumlar:
        raise ValueError("En az bir Durum seçilmeli")

    if progress:
        progress("Excel okunuyor…")
    items = read_options(xlsx_path, durumlar, buyer, klasman_w, cluster_f)
    if not items:
        raise ValueError(f"Seçilen filtrede opsiyon bulunamadı (Durum: {', '.join(durumlar)}"
                         f"; Buyer Grup: {', '.join(buyer) or 'tümü'}"
                         f"; Klasman: {', '.join(klasman_w) or 'tümü'}"
                         f"; Cluster: {', '.join(cluster_f) or 'tümü'})")

    # RANGE kontrol dosyası (son yüklenen) varsa Kumaş / Bitim / Paça / Yaka eklenir
    range_path = Path(range_path) if range_path else RANGE_FILE
    warnings = None
    if range_path.exists():
        if progress:
            progress("RANGE dosyası eşleştiriliyor…")
        warnings = apply_range(items, load_range(range_path))

    # PDF statik olduğu için açılış görünümü (ör. Çok İyi+İyi, K, BUC) basılır;
    # HTML tüm ürünleri içerir ve aynı görünümle açılır
    varsayilan = s.get("rapor_varsayilan") or {}
    pdf_items = default_view(items, varsayilan)

    img_ok = 0
    for it in items:
        it["img_path"] = None
    if download_images and "resim" not in gizli:
        if progress:
            progress(f"{len(pdf_items)} opsiyonun görselleri indiriliyor…")
        img_ok = fetch_images(pdf_items, progress=progress,
                              size=(600, 800) if big else (300, 400))

    week = week_label(source_name)
    title = f"LCW Opsiyon Performans Raporu{' — ' + week if week else ''}"
    subtitle = (f"Durum: {', '.join(durumlar)}   ·   Buyer Grup: {', '.join(buyer) or 'Tümü'}"
                f"   ·   Klasman: {', '.join(klasman_w) or 'Tümü'}"
                f"   ·   Cluster: {', '.join(cluster_f) or 'Tümü'}"
                f"   ·   Kırılım: Merch Alt Grup › Gelecek Dönem Ürün Klasman"
                f"   ·   Kaynak: {source_name}")

    if out_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w.-]+", "_", Path(source_name).stem).strip("_") or "rapor"
        out_path = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M}_{stem}.pdf"
    out_path = Path(out_path)

    if progress:
        progress("PDF oluşturuluyor…")
    pdf_codes = {it["option_kod"] for it in pdf_items}
    pdf_warn = None if warnings is None else [w for w in warnings if w["option_kod"] in pdf_codes]
    view_txt = " · ".join(f"{lab}: {', '.join(varsayilan[k])}" for k, lab in
                          (("buyer", "Buyer Grup"), ("merch_alt_grup", "Merch Alt Grup"),
                           ("klasman", "Klasman"),
                           ("cluster", "Cluster"),
                           ("durum", "Durum")) if varsayilan.get(k))
    pdf_subtitle = subtitle + (f"   ·   Görünüm: {view_txt}" if view_txt else "")
    pages = _Report(pdf_items, gizli, title, pdf_subtitle, out_path, big=big,
                    warnings=pdf_warn).render()
    # Aynı içeriğin HTML sürümü: bilgisayarda açılınca görseller lcw.com'dan yüklenir
    html_path = render_html(items, gizli, title, subtitle, out_path.with_suffix(".html"),
                            warnings=warnings, varsayilan=varsayilan)

    summary = {
        "pdf": out_path.name,
        "html": html_path.name,
        "kaynak": source_name,
        "hafta": week,
        "opsiyon": len(items),
        "pdf_opsiyon": len(pdf_items),
        "gorsel": img_ok,
        "range": range_path.name if warnings is not None else None,
        "range_uyari": len(warnings or []),
        "sayfa": pages,
        "durumlar": durumlar,
        "gizli_alanlar": gizli,
        "buyer_gruplar": buyer,
        "klasman_kelimeler": klasman_w,
        "clusterlar": cluster_f,
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


def accept_upload(data: bytes, filename: str):
    """Yüklenen Excel'i türüne göre kaydeder.
    RANGE kontrol dosyası → data/merch_range.xlsx (her gün güncellenebilir),
    haftalık dosya → uploads/ + son haftalık dosya olarak hatırlanır.
    Döner: ("range" | "hafta", path)"""
    path = save_upload(data, filename)
    if is_range_file(path):
        path.unlink(missing_ok=True)
        return "range", save_range(data)
    with _settings_lock:
        st = load_settings()
        st["son_hafta"] = {"path": str(path), "ad": Path(filename).name}
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    return "hafta", path


def last_weekly():
    """Son yüklenen haftalık dosya (path, ad) veya None."""
    son = load_settings().get("son_hafta") or {}
    p = Path(son.get("path", ""))
    return (p, son.get("ad") or p.name) if son and p.exists() else None


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
    ap.add_argument("--buyer", help="Virgüllü buyer grup listesi ('hepsi' = filtre yok)")
    ap.add_argument("--cluster", help="Virgüllü cluster listesi, ör. K veya G,K ('hepsi' = filtre yok)")
    ap.add_argument("--range", help="RANGE kontrol dosyası (varsayılan: son yüklenen)")
    ap.add_argument("--normal-gorsel", action="store_true", help="Küçük kartlar (sayfada 12)")
    ap.add_argument("--resimsiz", action="store_true", help="Görselleri indirme")
    a = ap.parse_args()
    p, summ = build_report(
        a.xlsx, out_path=a.out,
        durumlar=[d.strip() for d in a.durum.split(",")] if a.durum else None,
        gizli_alanlar=[g.strip() for g in a.gizle.split(",")] if a.gizle else None,
        buyer_gruplar=(([] if a.buyer.strip().lower() == "hepsi" else
                        [b.strip() for b in a.buyer.split(",")]) if a.buyer else None),
        clusterlar=(([] if a.cluster.strip().lower() == "hepsi" else
                     [c.strip() for c in a.cluster.split(",")]) if a.cluster else None),
        buyuk_gorsel=False if a.normal_gorsel else None,
        range_path=a.range,
        download_images=not a.resimsiz, progress=print)
    print(json.dumps(summ, ensure_ascii=False, indent=2))
