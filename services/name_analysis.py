"""
İsim analizi (ManyChat yorum → DM otomasyonu için)
──────────────────────────────────────────────────
Takipçi Reels'in altına adını yazar; ManyChat bu yorumu yakalayıp
/api/manychat/isim adresine sorar, buradan dönen kişiye özel metni DM
olarak gönderir.

İsmin numeroloji sayısı (Pisagor harf değerleri) kodla hesaplanır, Claude
kısa ve sıcak bir yorum yazar. Aynı isim için cevap önbellekte tutulur
(aynı adı yazan herkese aynı kalitede, maliyetsiz cevap).
"""

import os
import re
import json
import logging
import threading
from pathlib import Path

from services.tr_locale import tr_lower

log = logging.getLogger(__name__)

_TR_MAP = str.maketrans("çğıöşüâîû", "cgiosuaiu")
_VALUES = {c: (i % 9) + 1 for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
_lock = threading.Lock()

MEANINGS = {
    1: "lider, öncü, bağımsız", 2: "uyumlu, sezgisel, diplomat",
    3: "yaratıcı, neşeli, iletişimci", 4: "sağlam, çalışkan, güvenilir",
    5: "özgür ruhlu, maceracı, meraklı", 6: "şefkatli, koruyucu, sevgi dolu",
    7: "derin düşünen, sezgisi güçlü, gizemli",
    8: "güçlü, hırslı, bolluk çeken", 9: "bilge, merhametli, ilham veren",
    11: "usta sayı: yüksek sezgi ve ilham", 22: "usta sayı: büyük işler kuran",
}


def extract_name(text: str) -> str:
    """Yorumdan ilk ismi çıkarır ("Benim adım ayşe 😍" → "Ayşe")."""
    text = re.sub(r"(?i)\b(benim|adım|adim|ismim|ben)\b", " ", text or "")
    for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]{2,20}", text):
        low = tr_lower(w)
        return low[:1].replace("i", "İ").upper() + low[1:] if low else ""
    return ""


def name_number(name: str) -> int:
    letters = [c for c in tr_lower(name).translate(_TR_MAP) if c in _VALUES]
    n = sum(_VALUES[c] for c in letters)
    while n > 9 and n not in (11, 22):
        n = sum(int(d) for d in str(n))
    return n or 1


def _cache_file() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "name_analysis.json"


def _load() -> dict:
    try:
        return json.loads(_cache_file().read_text())
    except Exception:
        return {}


def analyze(comment: str) -> str:
    """Yorum metninden DM metni üretir."""
    name = extract_name(comment)
    if not name:
        return ("Merhaba! 🌙 İsim analizin için Reels'in altına sadece "
                "adını yaz, sana özel yorumu hemen göndereyim ✨")
    key = tr_lower(name)
    with _lock:
        cached = _load().get(key)
    if cached:
        return cached

    num = name_number(name)
    prompt = f"""Bir Instagram takipçisine DM ile kısa İSİM ANALİZİ yaz.
İsim: {name}
Numerolojide isim sayısı: {num} ({MEANINGS.get(num, '')})

Kurallar: Samimi, sıcak, "sen" diliyle; 4-5 kısa cümle. İsmin anlamını
biliyorsan bir cümleyle söyle (bilmiyorsan uydurma, atla). Sayının
kişiliğe ve aşka etkisini anlat. Sonunda: "Günlük burç yorumların için
takipte kal 💫" Emojiyi az kullan. Sadece mesaj metnini yaz."""
    try:
        from services.content import call_llm_with_fallback
        text, _ = call_llm_with_fallback(prompt, max_tokens=500)
        text = text.strip().strip('"')
    except Exception as e:
        log.warning(f"İsim analizi LLM hatası: {e}")
        return (f"{name}, isim sayın {num} ✨ Bu sayı {MEANINGS.get(num)} "
                f"bir enerji taşıyor. Günlük burç yorumların için takipte "
                f"kal 💫")
    with _lock:
        data = _load()
        data[key] = text
        _cache_file().parent.mkdir(parents=True, exist_ok=True)
        _cache_file().write_text(json.dumps(data, ensure_ascii=False))
    return text
