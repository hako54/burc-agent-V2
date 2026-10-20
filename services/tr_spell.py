"""
Ekranda/başlıkta görünecek kısa Türkçe metinlerin son imla kontrolü.

Yapay zekâ özellikle BÜYÜK harfle yazarken Türkçe karakterleri karıştırıyor
("HUZURUN DİLİ" yerine "HÜZURÜN DILI" gibi). Kısa metinler yayından önce
ikinci, ucuz bir LLM çağrısıyla düzeltilir. Herhangi bir sorun olursa
metinler olduğu gibi döner (üretim asla bu yüzden durmaz).
"""

import json
import logging

log = logging.getLogger(__name__)

_PROMPT = """Aşağıdaki Türkçe metinlerdeki YAZIM ve TÜRKÇE KARAKTER hatalarını düzelt
(ı/i, İ/I, ü/u, ö/o, ş/s, ç/c, ğ/g, eksik/fazla harf).
KURALLAR:
- Kelimeleri, anlamı, emojileri ve noktalamayı DEĞİŞTİRME; sadece yanlış
  yazılmış harfleri düzelt.
- Büyük/küçük harf düzenini koru. BÜYÜK harfli metinde doğru Türkçe büyük
  harfleri kullan (i → İ, ı → I).
- Metin zaten doğruysa aynen geri ver.
Sadece aynı sırada, aynı sayıda öğeli bir JSON dizisi döndür.

Metinler:
{items}"""


def fix_turkish(texts: list) -> list:
    """Metin listesini düzeltilmiş hâliyle döner (sıra ve sayı korunur)."""
    idx = [i for i, t in enumerate(texts) if isinstance(t, str) and t.strip()]
    if not idx:
        return texts
    src = [texts[i] for i in idx]
    try:
        from services.content import call_llm_with_fallback
        raw, _ = call_llm_with_fallback(
            _PROMPT.format(items=json.dumps(src, ensure_ascii=False)),
            max_tokens=800)
        raw = raw.strip()
        start, end = raw.find("["), raw.rfind("]")
        fixed = json.loads(raw[start:end + 1])
        if not isinstance(fixed, list) or len(fixed) != len(src):
            raise ValueError("liste uzunluğu uyuşmuyor")
    except Exception as e:
        log.warning(f"İmla kontrolü atlandı: {e}")
        return texts
    out = list(texts)
    for i, old, new in zip(idx, src, fixed):
        # Güvenlik: anlamı değiştiren büyük farkları kabul etme
        if (isinstance(new, str) and new.strip()
                and abs(len(new) - len(old)) <= max(4, len(old) * 0.25)):
            if new != old:
                log.info(f"✏️ İmla düzeltildi: {old!r} → {new!r}")
            out[i] = new
    return out
