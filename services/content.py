"""
İçerik Üretim Servisi
Claude → Gemini → Groq fallback zinciri ile günlük burç yorumu üretir.
Her LLM çağrısı ayrı fonksiyon, hata ayıklaması kolay.
Üretilen metin post-process ile imla hatalarından arındırılır.
"""

import os
import json
import re
import logging
from datetime import datetime
from typing import Optional

from zodiac import get_sign
from services.text_cleaner import clean_content

log = logging.getLogger(__name__)


def _build_prompt(sign_key: str, used_themes: list = None) -> str:
    """Belirli bir burç için günlük yorum üretme prompt'u."""
    info = get_sign(sign_key)
    today = datetime.now().strftime("%d %B %Y")
    used = ", ".join(used_themes[-10:]) if used_themes else "yok"

    return f"""Sen profesyonel bir Türk astroloğusun. YouTube Shorts için 60 saniyelik
günlük burç yorumu hazırlıyorsun.

Tarih: {today}
Burç: {info['name']} {info['symbol']} ({info['dates']})
Element: {info['element']}, Yönetici: {info['ruler']}
Özellikler: {info['traits']}

Bugün için pozitif ama gerçekçi, enerji veren, motive edici ama abartısız
bir günlük yorum yaz. Astroloji dilini akıcı Türkçe kullan, klişelerden
kaçın ("dikkatli ol", "fırsatlar kapıda" gibi bayat ifadeler kullanma).

Son kullanılan temalar (BUNLARI TEKRARLAMA): {used}

══════════════════════════════════════════════════════════════════
TÜRKÇE İMLA VE YAZIM KURALLARI — KESİNLİKLE UYGULA
══════════════════════════════════════════════════════════════════

1. BAĞLAÇLARIN YAZIMI:
   ✅ "de / da" bağlacı AYRI yazılır: "bugün de", "sen de", "bu da"
   ❌ YANLIŞ: "bugünde" (kelimede bağlaç anlamı varsa ayrı)
   ✅ "ki" bağlacı AYRI yazılır: "inan ki", "öyle ki"
   ✅ "mi / mı / mu / mü" soru eki AYRI: "geliyor mu", "olur mu"

2. BİRLEŞİK KELİMELER:
   ✅ "bir şey" (ayrı), "hiçbir", "herhangi", "herkes"
   ✅ "hâlâ" (şapkalı a), "kâr", "kâğıt", "lâzım"

3. YAYGIN HATALAR (KESİNLİKLE YAPMA):
   ❌ "yalnış" → ✅ "yanlış"
   ❌ "herkez" → ✅ "herkes"
   ❌ "yanlız" → ✅ "yalnız"
   ❌ "çünki" → ✅ "çünkü"
   ❌ "eğerki" → ✅ "eğer"
   ❌ "birşey" → ✅ "bir şey"
   ❌ "hiçbirşey" → ✅ "hiçbir şey"

4. NOKTALAMA:
   - Her cümle nokta, soru veya ünlem ile bitsin
   - Virgülden ve noktadan sonra bir boşluk bırak
   - Tırnak ("") kullanma — JSON yapısını bozar

5. TTS İÇİN:
   - Rakamları yazıyla yaz: 3 → "üç"
   - Kısaltma yapma: "vs." → "ve benzerleri"
   - Akıcı ve doğal cümleler — okunurken doğal tınlasın

══════════════════════════════════════════════════════════════════

Sadece JSON döndür (başka hiçbir şey yazma):
{{
  "title": "Başlık (max 90 karakter, burç adı + tarih + emoji ile, merak uyandıran)",
  "hook": "İlk 3 saniye - izleyiciyi bağlayacak giriş cümlesi (burç adını söyle)",
  "segments": [
    {{"time": "0-4s", "section": "giris", "text": "Kısa altyazı", "narration": "TTS metni - burç adı + günün enerjisi"}},
    {{"time": "4-15s", "section": "genel", "text": "Kısa altyazı", "narration": "Günün genel yorumu - 2-3 cümle"}},
    {{"time": "15-28s", "section": "ask", "text": "💕 Aşk", "narration": "Aşk hayatı için günün mesajı - 2 cümle"}},
    {{"time": "28-40s", "section": "kariyer", "text": "💼 Kariyer", "narration": "İş ve kariyer yorumu - 2 cümle"}},
    {{"time": "40-50s", "section": "saglik", "text": "🌿 Sağlık", "narration": "Sağlık ve enerji yorumu - 1-2 cümle"}},
    {{"time": "50-60s", "section": "sans", "text": "✨ Şanslı", "narration": "Şanslı sayı, renk ve uyumlu burcu belirt"}}
  ],
  "full_narration": "Tüm anlatım metni tek parça (TTS yedek, 180-240 kelime)",
  "lucky_number": "1-99 arası tek sayı, string olarak",
  "lucky_color": "Şanslı renk (Türkçe, tek kelime)",
  "compatible_sign": "Bugün uyumlu olduğu burç (12 burçtan biri)",
  "theme": "Bugünkü yorumun kısa teması (3-5 kelime)",
  "description": "YouTube açıklaması (200-300 karakter, hashtag'siz)",
  "tags": ["burç", "{info['name'].lower()}", "günlük", "astroloji", "shorts"],
  "hashtags": ["#{info['name'].lower()}burcu", "#günlükburç", "#astroloji", "#shorts"]
}}

ÖNEMLİ:
- Her segment için narration mutlaka dolu olmalı.
- compatible_sign: Koç, Boğa, İkizler, Yengeç, Aslan, Başak, Terazi, Akrep, Yay, Oğlak, Kova, Balık — birinden biri."""


def _parse_json(text: str) -> dict:
    """LLM çıktısından JSON'u ayıklar. Kontrol karakterlerini temizler."""
    # Markdown code block'ları kaldır
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    text = text.strip()

    # String değerlerin içindeki kontrol karakterlerini escape et
    # (Özellikle Llama/Groq bazen kaçışsız \n, \r, \t bırakır)
    def fix_controls(match):
        inner = match.group(0)
        inner = inner.replace("\r\n", "\\n").replace("\n", "\\n")
        inner = inner.replace("\r", "\\n").replace("\t", " ")
        return inner

    text = re.sub(r'"(?:[^"\\]|\\.)*"', fix_controls, text, flags=re.DOTALL)
    return json.loads(text)


def _call_claude(prompt: str) -> str:
    """Anthropic Claude API çağrısı."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY eksik")

    import anthropic
    import httpx

    # SSL verify=False kurumsal proxyleri bypass etmek için
    client = anthropic.Anthropic(
        api_key=api_key,
        http_client=httpx.Client(verify=False, timeout=60),
    )
    # Haiku 4.5 — ucuz, hızlı, burç yorumu için yeterli
    msg = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5"),
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _call_gemini(prompt: str) -> str:
    """Google Gemini API çağrısı. Birden fazla model dener."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY eksik")

    import requests

    models = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-flash-latest",
    ]
    last_error = None

    for model in models:
        try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/"
                f"models/{model}:generateContent?key={api_key}"
            )
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 3000,
                    "temperature": 0.9,
                },
            }
            r = requests.post(url, json=body, timeout=60, verify=False)

            if r.status_code == 200:
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                log.info(f"Gemini {model} başarılı")
                return text.strip()

            last_error = f"HTTP {r.status_code}"
            log.warning(f"Gemini {model} {last_error}")
        except Exception as e:
            last_error = str(e)
            log.warning(f"Gemini {model} hata: {e}")

    raise RuntimeError(f"Tüm Gemini modelleri başarısız: {last_error}")


def _call_groq(prompt: str) -> str:
    """Groq (Llama 3.3 70B) API çağrısı."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY eksik")

    import requests

    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 3000,
            "temperature": 0.9,
        },
        timeout=60,
        verify=False,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Groq HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"].strip()


def generate_content(sign_key: str, used_themes: list = None) -> dict:
    """Verilen burç için günlük yorum içeriği üretir.
    Claude → Gemini → Groq fallback. Hepsi başarısız olursa exception fırlatır."""
    info = get_sign(sign_key)
    prompt = _build_prompt(sign_key, used_themes)

    log.info(f"{info['name']} burcu için içerik üretiliyor...")

    # Provider sırası
    providers = [
        ("Claude", _call_claude),
        ("Gemini", _call_gemini),
        ("Groq", _call_groq),
    ]
    errors = []

    for name, fn in providers:
        try:
            log.info(f"  → {name} deneniyor...")
            raw = fn(prompt)
            content = _parse_json(raw)
            log.info(f"  ✅ {name} başarılı")

            # Türkçe imla post-processing
            content = clean_content(content)

            # Meta bilgileri ekle
            content.update({
                "sign_key": sign_key,
                "sign_name": info["name"],
                "sign_symbol": info["symbol"],
                "sign_emoji": info["emoji"],
                "sign_dates": info["dates"],
                "element": info["element"],
                "accent_color": info["color"],
                "background_color": info["bg"],
                "date": datetime.now().strftime("%d %B %Y"),
                "generated_at": datetime.now().isoformat(),
                "provider": name,
            })
            # Görsel arama sorgularını ekle
            content["pexels_queries"] = info["visual_queries"] + [
                f"zodiac {info['en_name']} mystical",
                "astrology stars cosmic",
            ]
            return content

        except Exception as e:
            log.warning(f"  ⚠ {name} başarısız: {str(e)[:150]}")
            errors.append(f"{name}: {str(e)[:100]}")

    raise RuntimeError(
        f"Tüm içerik üretim servisleri başarısız. Detaylar: {' | '.join(errors)}"
    )
