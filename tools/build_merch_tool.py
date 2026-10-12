"""
Merch Rapor Oluşturucu (tek dosyalık, bilgisayarda çalışan araç) üretir.

    python tools/build_merch_tool.py            → tools/Merch_Rapor_Olusturucu.html

Çıkan HTML dosyası çift tıklanınca tarayıcıda açılır; haftalık Excel ve
RANGE kontrol dosyası bırakılınca rapor bilgisayarda (sunucusuz) hazırlanır.
Rapor görünümü services/merch_report.py'deki HTML şablonunun aynısıdır.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import merch_report as m  # noqa: E402

TOOLS = ROOT / "tools"


def js(v):
    # </script> içeren metinler script bloğunu kapatmasın
    return json.dumps(v, ensure_ascii=False).replace("</", "<\\/")


def build(out_path=TOOLS / "Merch_Rapor_Olusturucu.html"):
    tpl = (TOOLS / "merch_tool_template.html").read_text(encoding="utf-8")
    xlsx_js = (TOOLS / "vendor" / "xlsx.full.min.js").read_text(encoding="utf-8")
    defaults = {k: m.DEFAULT_SETTINGS[k] for k in
                ("durumlar", "buyer_gruplar", "klasman_kelimeler", "clusterlar")}
    parts = {
        "@@TOOL_FIELDS@@": js([[k, lab, col] for k, (lab, col) in m.FIELDS.items()]),
        "@@TOOL_DURUM@@": js(m.ALL_DURUM),
        "@@TOOL_DEFAULTS@@": js(defaults),
        "@@TOOL_COLORS@@": js(m.DURUM_COLORS),
        "@@TOOL_ORDER@@": js(m.DURUM_ORDER),
        "@@TOOL_BUYER_COL@@": js(m.BUYER_COL),
        # Rapor şablonu ve kütüphane en son: içerikleri başka yer tutucu
        # gibi görünen metin barındırabilir, tekrar taranmasınlar
        "@@TOOL_REPORT_TEMPLATE@@": js(m._HTML_TEMPLATE),
        "@@TOOL_XLSX_JS@@": xlsx_js.replace("</script", "<\\/script"),
    }
    for key, val in parts.items():
        assert tpl.count(key) == 1, key
        tpl = tpl.replace(key, val, 1)
    Path(out_path).write_text(tpl, encoding="utf-8")
    return Path(out_path)


if __name__ == "__main__":
    p = build(sys.argv[1] if len(sys.argv) > 1 else TOOLS / "Merch_Rapor_Olusturucu.html")
    print(f"✓ {p} ({p.stat().st_size / 1e6:.1f} MB)")
