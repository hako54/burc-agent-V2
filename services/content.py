"""
services/content.py — LLM içerik üretimi + fallback
Claude → Gemini → Groq sırasıyla dener.
parse_llm_json bozuk JSON'ları da onarabilecek şekilde dayanıklı.
"""

import os
import json
import re
import logging

log = logging.getLogger(__name__)


def parse_llm_json(text: str) -> dict:
    """LLM'in ürettiği JSON metnini parse eder.
    Bozuk JSON'ları da onarmaya çalışır — Gemini ve diğer modellerden
    gelen yaygın format sorunlarını handle eder.
    """
    if not text:
        raise ValueError("Boş metin")

    text = text.strip()

    # 1) Markdown code block'ları temizle: ```json ... ``` veya ``` ... ```
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*```\s*$', '', text)
    text = text.strip()

    # 2) JSON objesi başlangıcını bul ({ veya [)
    obj_start = text.find('{')
    arr_start = text.find('[')
    if obj_start == -1 and arr_start == -1:
        raise ValueError(f"JSON bulunamadı: {text[:200]}")
    if obj_start == -1:
        start_idx = arr_start
    elif arr_start == -1:
        start_idx = obj_start
    else:
        start_idx = min(obj_start, arr_start)
    text = text[start_idx:]

    # 3) İlk deneme — düz JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.warning(f"Direkt parse başarısız: {e}. Onarım denenecek.")

    # 4) Onarım — yaygın sorunları düzelt
    fixed = _try_repair_json(text)
    if fixed:
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            log.warning(f"Onarımdan sonra da parse başarısız: {e}")

    # 5) Son çare — JSON5-lite parse (kontrollü)
    try:
        # Tek tırnakları çift yap (JSON standart değil ama LLM'ler bazen kullanır)
        alt = re.sub(r"'([^']*)':", r'"\1":', text)
        return json.loads(alt)
    except Exception:
        pass

    # 6) Regex ile anahtar-değer çıkarma (en son çare)
    result = _extract_by_regex(text)
    if result:
        log.warning("Regex ile kısmi çıkarım yapıldı — bazı alanlar eksik olabilir")
        return result

    raise ValueError(f"JSON parse edilemedi: {text[:300]}...")


def _try_repair_json(text: str) -> str:
    """Yaygın LLM JSON hatalarını onarır."""
    # 1) Kaçırılmamış newline'ları string içinde escape et
    # Örnek: "narration": "Bu bir metin
    # yeni satır" → "narration": "Bu bir metin\nyeni satır"
    fixed = _escape_string_newlines(text)

    # 2) Sondaki fazla virgülleri kaldır
    # { "a": 1, } → { "a": 1 }
    fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)

    # 3) Trailing text'i kes — son } veya ]'den sonrasını at
    last_brace = max(fixed.rfind('}'), fixed.rfind(']'))
    if last_brace > 0:
        fixed = fixed[:last_brace + 1]

    # 4) Eğer JSON eksik kapatılmış (parantez sayısı hatası)
    open_braces = fixed.count('{')
    close_braces = fixed.count('}')
    open_brackets = fixed.count('[')
    close_brackets = fixed.count(']')

    if open_brackets > close_brackets:
        fixed += ']' * (open_brackets - close_brackets)
    if open_braces > close_braces:
        fixed += '}' * (open_braces - close_braces)

    return fixed


def _escape_string_newlines(text: str) -> str:
    """String değerlerin içindeki kaçırılmamış newline'ları escape eder.
    Örneğin: "value": "abc
    def" → "value": "abc\\ndef"
    """
    result = []
    in_string = False
    escape_next = False
    i = 0
    while i < len(text):
        ch = text[i]
        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue
        if ch == '\\':
            result.append(ch)
            escape_next = True
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue
        if in_string:
            # String içindeyken newline/tab/CR → escape
            if ch == '\n':
                result.append('\\n')
            elif ch == '\r':
                result.append('\\r')
            elif ch == '\t':
                result.append('\\t')
            else:
                result.append(ch)
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


def _extract_by_regex(text: str) -> dict:
    """Son çare: temel alanları regex ile çıkar."""
    result = {}
    # "key": "value" formatını yakala (string değerler)
    pattern = r'"([^"]+)"\s*:\s*"((?:[^"\\]|\\.)*)"'
    for match in re.finditer(pattern, text):
        key = match.group(1)
        value = match.group(2)
        # Escape'leri geri çevir
        value = value.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
        result[key] = value
    # "key": [array] formatı (basit)
    array_pattern = r'"([^"]+)"\s*:\s*\[([^\]]*)\]'
    for match in re.finditer(array_pattern, text):
        key = match.group(1)
        arr_text = match.group(2)
        items = re.findall(r'"([^"]+)"', arr_text)
        if items and key not in result:
            result[key] = items
    return result if result else None


def call_llm_with_fallback(prompt: str, max_tokens: int = 2500):
    """Sıralı olarak Claude → Gemini → Groq dener.
    (raw_text, provider_name) döner.
    """
    errors = []

    # 1) Claude
    try:
        raw = _call_claude(prompt, max_tokens)
        if raw:
            log.info("  ✅ Claude başarılı")
            return raw, "claude"
    except Exception as e:
        log.warning(f"  ⚠ Claude başarısız: {str(e)[:200]}")
        errors.append(f"Claude: {e}")

    # 2) Gemini
    try:
        raw = _call_gemini(prompt, max_tokens)
        if raw:
            log.info("  ✅ Gemini başarılı")
            return raw, "gemini"
    except Exception as e:
        log.warning(f"  ⚠ Gemini başarısız: {str(e)[:200]}")
        errors.append(f"Gemini: {e}")

    # 3) Groq
    try:
        raw = _call_groq(prompt, max_tokens)
        if raw:
            log.info("  ✅ Groq başarılı")
            return raw, "groq"
    except Exception as e:
        log.warning(f"  ⚠ Groq başarısız: {str(e)[:200]}")
        errors.append(f"Groq: {e}")

    raise RuntimeError(f"Tüm LLM'ler başarısız: {'; '.join(errors)}")


def _call_claude(prompt: str, max_tokens: int) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY yok")
    log.info("  → Claude deneniyor...")
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    model = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-haiku-4-5"
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if msg.stop_reason == "max_tokens":
        # Yarım JSON'u "onarıp" eksik içerikle devam etmek yerine
        # sonraki sağlayıcıya düş
        raise RuntimeError(f"Claude yanıtı max_tokens'ta kesildi ({model})")
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"Claude isteği reddetti ({model})")
    return "".join(b.text for b in msg.content if b.type == "text")


def _call_gemini(prompt: str, max_tokens: int) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY yok")
    log.info("  → Gemini deneniyor...")
    import requests

    # Modelleri sırayla dene
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    last_error = None
    for model in models:
        try:
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={api_key}")
            generation_config = {
                "temperature": 0.85,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            }
            if model.startswith("gemini-2.5"):
                # 2.5 modellerinde düşünme token'ları maxOutputTokens'tan
                # yer; kapatmazsak JSON yarıda kesiliyor
                generation_config["thinkingConfig"] = {"thinkingBudget": 0}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": generation_config,
            }
            r = requests.post(url, json=payload, timeout=45)
            if r.status_code == 200:
                data = r.json()
                candidates = data.get("candidates", [])
                if candidates:
                    finish = candidates[0].get("finishReason", "")
                    if finish and finish != "STOP":
                        last_error = f"{model}: finishReason={finish}"
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        log.info(f"Gemini {model} başarılı")
                        return parts[0].get("text", "")
            last_error = f"{model}: HTTP {r.status_code}"
        except Exception as e:
            last_error = f"{model}: {e}"
            continue
    raise RuntimeError(f"Gemini tüm modeller başarısız: {last_error}")


def _call_groq(prompt: str, max_tokens: int) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY yok")
    log.info("  → Groq deneniyor...")
    import requests
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system",
             "content": "Sadece geçerli JSON döndür, başka hiçbir şey yazma."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.85,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json=payload, timeout=45,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError("Groq yanıtı max_tokens'ta kesildi")
    return choice["message"]["content"]
