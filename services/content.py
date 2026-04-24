"""
LLM Servisi (Generic)
İçerik tipinden bağımsız. Verilen prompt'u Claude → Gemini → Groq
zinciriyle dener. JSON parse etmek ayrı fonksiyon.

Eski kodların import'ları için generate_content fonksiyonu da korunuyor.
"""

import os
import json
import re
import logging
from datetime import datetime

log = logging.getLogger(__name__)


def parse_llm_json(text: str) -> dict:
    """LLM çıktısından JSON'u ayıklar. Kontrol karakterlerini temizler."""
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    text = text.strip()

    def fix_controls(match):
        inner = match.group(0)
        inner = inner.replace("\r\n", "\\n").replace("\n", "\\n")
        inner = inner.replace("\r", "\\n").replace("\t", " ")
        return inner

    text = re.sub(r'"(?:[^"\\]|\\.)*"', fix_controls, text, flags=re.DOTALL)
    return json.loads(text)


def _call_claude(prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY eksik")

    import anthropic
    import httpx

    client = anthropic.Anthropic(
        api_key=api_key,
        http_client=httpx.Client(verify=False, timeout=60),
    )
    msg = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5"),
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _call_gemini(prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY eksik")

    import requests
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]
    last_error = None
    for model in models:
        try:
            url = (f"https://generativelanguage.googleapis.com/v1beta/"
                   f"models/{model}:generateContent?key={api_key}")
            r = requests.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 3000,
                        "temperature": 0.9,
                    },
                },
                timeout=60, verify=False,
            )
            if r.status_code == 200:
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                log.info(f"Gemini {model} başarılı")
                return text.strip()
            last_error = f"HTTP {r.status_code}"
        except Exception as e:
            last_error = str(e)
    raise RuntimeError(f"Tüm Gemini modelleri başarısız: {last_error}")


def _call_groq(prompt: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY eksik")

    import requests
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 3000,
            "temperature": 0.9,
        },
        timeout=60, verify=False,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Groq HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"].strip()


def call_llm_with_fallback(prompt: str) -> tuple:
    """Prompt'u Claude → Gemini → Groq ile dener.
    Dönüş: (raw_text, provider_name)"""
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
            log.info(f"  ✅ {name} başarılı")
            return raw, name
        except Exception as e:
            log.warning(f"  ⚠ {name} başarısız: {str(e)[:150]}")
            errors.append(f"{name}: {str(e)[:100]}")
    raise RuntimeError(
        f"Tüm LLM servisleri başarısız. Detaylar: {' | '.join(errors)}"
    )


# ── Geriye uyumluluk: eski generate_content API'si ───────────────

def generate_content(sign_key: str, used_themes: list = None) -> dict:
    """Eski kodlar için — zodiac content type ile çalışır."""
    from zodiac import get_sign
    from content_types.zodiac import ZodiacType
    from services.text_cleaner import clean_content as _clean

    # Fake channel için burç kanalını kullan
    fake_channel = {"id": "burc", "name": "Burç Kanalı", "type": "zodiac"}
    zt = ZodiacType(fake_channel)
    prompt = zt.build_prompt(sign_key, used_themes=used_themes)
    raw, provider = call_llm_with_fallback(prompt)
    content = parse_llm_json(raw)
    content = _clean(content)

    info = get_sign(sign_key)
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
        "provider": provider,
    })
    content["pexels_queries"] = info["visual_queries"] + [
        f"zodiac {info['en_name']} mystical",
        "astrology stars cosmic",
    ]
    return content
