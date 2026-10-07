"""
Türkçe Metin Post-Processor
LLM'in ürettiği metindeki yaygın imla ve noktalama hatalarını düzeltir.
Aggressive değil — sadece net yanlışları düzeltir, anlama dokunmaz.
"""

import re
import logging

from services.tr_locale import tr_upper

log = logging.getLogger(__name__)

# ── Yaygın Kelime Hataları ──────────────────────────────────────────
# (hatalı, doğru) — case-insensitive eşleşir, case korunur
WORD_FIXES = [
    # Yaygın yazım hataları
    (r"\byalnış\b", "yanlış"),
    (r"\bYalnış\b", "Yanlış"),
    (r"\bherkez\b", "herkes"),
    (r"\bHerkez\b", "Herkes"),
    (r"\byanlız\b", "yalnız"),
    (r"\bYanlız\b", "Yalnız"),
    (r"\bçünki\b", "çünkü"),
    (r"\bÇünki\b", "Çünkü"),
    (r"\beğerki\b", "eğer"),
    (r"\bEğerki\b", "Eğer"),
    # "bir şey" tüm türevleri
    (r"\bbirşey\b", "bir şey"),
    (r"\bBirşey\b", "Bir şey"),
    (r"\bhiçbirşey\b", "hiçbir şey"),
    (r"\bHiçbirşey\b", "Hiçbir şey"),
    (r"\bherşey\b", "her şey"),
    (r"\bHerşey\b", "Her şey"),
    # Şapkalı harf düzeltmeleri (yaygın yazım)
    (r"\bhala\b", "hâlâ"),
    (r"\bHala\b", "Hâlâ"),
    # "de/da" - yaygın yanlış bitişik yazımlar
    # Bu karmaşık, sadece çok net olanları düzeltiyoruz
    # "bugünde" + kelime sınırı = "bugün de" (bağlaç)
    (r"\bbugünde\b", "bugün de"),
    (r"\bBugünde\b", "Bugün de"),
    (r"\byarında\b", "yarın da"),
    (r"\bYarında\b", "Yarın da"),
    # "ki" bağlacı - net olanlar
    (r"\bçünkü ki\b", "çünkü"),
    (r"\bÇünkü ki\b", "Çünkü"),
]


# ── Noktalama ve Boşluk Düzeltmeleri ────────────────────────────────
# (desen, replacement)
PUNCTUATION_FIXES = [
    # Virgülden sonra boşluk (ondalık sayılara dokunma: 3,5)
    (r"(?<!\d),(?!\d)([^\s,])", r", \1"),
    # Noktadan sonra boşluk — sadece büyük harfle yeni cümle başlıyorsa
    # (2.5 veya youtube.com gibi ifadelere dokunma)
    (r"\.([A-ZĞÜŞİÖÇ])", r". \1"),
    # Soru ve ünlemden sonra boşluk
    (r"\?([a-zA-ZğüşıöçĞÜŞİÖÇ])", r"? \1"),
    (r"!([a-zA-ZğüşıöçĞÜŞİÖÇ])", r"! \1"),
    # Çift boşlukları tek boşluğa indir
    (r"  +", " "),
    # Noktadan önce boşluk varsa kaldır
    (r"\s+([.,!?;:])", r"\1"),
    # Birden fazla nokta (...) dokunma, ama ".." → "."
    (r"(?<!\.)\.\.(?!\.)", "."),
]


# ── Cümle sonu kontrolü ─────────────────────────────────────────────

def _ensure_sentence_end(text: str) -> str:
    """Metin nokta/soru/ünlem ile bitmiyorsa nokta ekler."""
    text = text.rstrip()
    if not text:
        return text
    last = text[-1]
    if last not in ".!?":
        # Ama parantez veya tırnakla bitiyorsa ondan öncesini kontrol et
        if len(text) >= 2 and text[-1] in ")\"'”’" and text[-2] not in ".!?":
            text = text[:-1] + "." + text[-1]
        elif last not in ".!?…":
            text += "."
    return text


def _capitalize_sentence_starts(text: str) -> str:
    """Cümle başlarını büyük harf yap (nokta/ünlem/soru sonrası)."""
    def cap_match(m):
        return m.group(1) + tr_upper(m.group(2))

    # İlk harfi büyük yap
    text = re.sub(r"^(\s*)([a-zğüşıöç])", cap_match, text)
    # Noktadan sonra (boşlukla) gelen harfi büyük yap
    text = re.sub(r"([.!?]\s+)([a-zğüşıöç])", cap_match, text)
    return text


def clean_text(text: str) -> str:
    """Tek bir metin parçasını temizler."""
    if not text or not isinstance(text, str):
        return text

    # 1. Kelime hataları
    for pattern, replacement in WORD_FIXES:
        text = re.sub(pattern, replacement, text)

    # 2. Noktalama/boşluk
    for pattern, replacement in PUNCTUATION_FIXES:
        text = re.sub(pattern, replacement, text)

    # 3. Cümle başı büyük harf
    text = _capitalize_sentence_starts(text)

    # 4. Baş/son boşluk temizle
    text = text.strip()

    return text


def clean_narration(text: str) -> str:
    """TTS narration'ı için — daha agresif temizlik.
    Rakamları yazıya çevirir ve cümle sonunda nokta ekler."""
    text = clean_text(text)
    # Rakamları yazıya çevir
    text = _numbers_to_words(text)
    # Rakamlar değişince cümle başı yine kontrol edilsin
    text = _capitalize_sentence_starts(text)
    # Cümle sonu garanti
    text = _ensure_sentence_end(text)
    return text


def _numbers_to_words(text: str) -> str:
    """Metin içinde geçen rakamları Türkçe karşılıklarıyla değiştirir.
    Sadece 1-99 arası basit sayılar. Şanslı sayı gibi alanlarda kullanma."""
    numbers_map = {
        0: "sıfır", 1: "bir", 2: "iki", 3: "üç", 4: "dört",
        5: "beş", 6: "altı", 7: "yedi", 8: "sekiz", 9: "dokuz",
        10: "on", 11: "on bir", 12: "on iki", 13: "on üç",
        14: "on dört", 15: "on beş", 16: "on altı", 17: "on yedi",
        18: "on sekiz", 19: "on dokuz", 20: "yirmi",
    }

    def replace_number(match):
        try:
            n = int(match.group(0))
            if n in numbers_map:
                return numbers_map[n]
            # 21-99 arası
            if 21 <= n <= 99:
                tens = (n // 10) * 10
                ones = n % 10
                tens_names = {
                    20: "yirmi", 30: "otuz", 40: "kırk", 50: "elli",
                    60: "altmış", 70: "yetmiş", 80: "seksen", 90: "doksan",
                }
                if ones == 0:
                    return tens_names.get(tens, str(n))
                return tens_names.get(tens, "") + " " + numbers_map.get(ones, str(ones))
        except Exception:
            pass
        return match.group(0)  # dokunma

    # Standalone sayıları bul (kelime sınırları arasında)
    # Ama tarih/saat format'larına dokunma (2026, 10:00 gibi)
    return re.sub(r"\b\d{1,2}\b(?![:\-/])", replace_number, text)


def clean_content(content: dict) -> dict:
    """İçerik dict'indeki tüm metin alanlarını temizler."""
    if not isinstance(content, dict):
        return content

    # Normal metin alanları
    text_fields = ["title", "hook", "description", "theme",
                   "lucky_color", "compatible_sign"]
    for field in text_fields:
        if field in content and isinstance(content[field], str):
            content[field] = clean_text(content[field])

    # Narration alanları — daha agresif
    if "full_narration" in content and isinstance(content["full_narration"], str):
        content["full_narration"] = clean_narration(content["full_narration"])

    # Segments
    if "segments" in content and isinstance(content["segments"], list):
        for seg in content["segments"]:
            if not isinstance(seg, dict):
                continue
            if "text" in seg and isinstance(seg["text"], str):
                seg["text"] = clean_text(seg["text"])
            if "narration" in seg and isinstance(seg["narration"], str):
                seg["narration"] = clean_narration(seg["narration"])

    log.info("Metin post-processing tamamlandı")
    return content
