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


# ── Yedek sağlayıcılar: Gemini + Groq ─────────────────────────────
# Sağlayıcılar modelleri sık kaldırıyor. Önce env'deki (veya varsayılan)
# listeyi sırayla deneriz; hepsi "model yok" (404) derse sağlayıcının
# güncel model listesini çekip uygun bir model seçeriz. Böylece bir model
# kaldırıldığında üretim durmaz. Elle sabitlemek için Railway'de:
#   GEMINI_MODELS=gemini-2.5-flash,gemini-2.5-flash-lite
#   GROQ_MODELS=openai/gpt-oss-120b,openai/gpt-oss-20b
DEFAULT_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
DEFAULT_GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GROQ_BASE = "https://api.groq.com/openai/v1"

# Metin üretimi dışındaki model ailelerini otomatik seçimde ele
_SKIP_WORDS = ("embed", "image", "tts", "audio", "live", "vision", "guard",
               "whisper", "speech", "aqa", "learnlm", "robotics", "computer",
               "exp", "preview", "compound", "safeguard", "orpheus")


def _env_list(name: str, default: list) -> list:
    raw = os.environ.get(name, "")
    items = [m.strip() for m in raw.split(",") if m.strip()]
    return items or list(default)


def _version_key(name: str) -> tuple:
    """'gemini-3.1-flash' → (3, 1); sürüm yoksa (0,)."""
    m = re.search(r"(\d+(?:\.\d+)*)", name)
    if not m:
        return (0,)
    return tuple(int(x) for x in m.group(1).split("."))


def _discover_gemini_models(api_key: str, exclude: set) -> list:
    """Gemini'nin güncel model listesinden en yeni 'flash' modellerini seçer."""
    import requests
    try:
        r = requests.get(f"{GEMINI_BASE}/models", params={"pageSize": 200},
                         headers={"x-goog-api-key": api_key}, timeout=20)
        if r.status_code != 200:
            log.warning(f"Gemini model listesi alınamadı: HTTP {r.status_code}")
            return []
        found = []
        for m in r.json().get("models", []):
            name = m.get("name", "").removeprefix("models/")
            if ("generateContent" not in m.get("supportedGenerationMethods", [])
                    or not name.startswith("gemini-") or "flash" not in name
                    or any(w in name for w in _SKIP_WORDS) or name in exclude):
                continue
            found.append(name)
        # En yeni sürüm önce; aynı sürümde tam flash, lite'tan önce
        found.sort(key=lambda n: (_version_key(n), "lite" not in n),
                   reverse=True)
        log.info(f"Gemini otomatik model adayları: {found[:3]}")
        return found[:2]
    except Exception as e:
        log.warning(f"Gemini model listesi hatası: {type(e).__name__}")
        return []


def _gemini_generate(model: str, prompt: str, max_tokens: int,
                     api_key: str):
    """Tek bir Gemini modelini dener. (metin, hata, model_yok) döner."""
    import requests
    generation_config = {
        "temperature": 0.85,
        "maxOutputTokens": max_tokens,
        "responseMimeType": "application/json",
    }
    if model.startswith("gemini-2.5"):
        # 2.5'te düşünme token'ları maxOutputTokens'tan yer; kapatıyoruz
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    else:
        # Daha yeni modellerde düşünme kapatılamayabilir — pay bırak
        generation_config["maxOutputTokens"] = max_tokens * 4
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    try:
        # Anahtar URL yerine header'da — hata mesajlarına/loglara sızmasın
        r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent",
                          json=payload, timeout=60,
                          headers={"x-goog-api-key": api_key})
    except Exception as e:
        return None, f"{model}: {type(e).__name__}: {str(e)[:150]}", False
    if r.status_code != 200:
        return (None, f"{model}: HTTP {r.status_code} {r.text[:150]}",
                r.status_code == 404)
    candidates = r.json().get("candidates", [])
    if not candidates:
        return None, f"{model}: boş yanıt", False
    finish = candidates[0].get("finishReason", "")
    if finish and finish != "STOP":
        return None, f"{model}: finishReason={finish}", False
    parts = candidates[0].get("content", {}).get("parts", [])
    # Düşünme özeti parçalarını atla, sadece cevap metni
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        return None, f"{model}: boş metin", False
    return text, None, False


def _call_gemini(prompt: str, max_tokens: int) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY yok")
    log.info("  → Gemini deneniyor...")

    errors = []
    tried = []
    all_missing = True
    for model in _env_list("GEMINI_MODELS", DEFAULT_GEMINI_MODELS):
        tried.append(model)
        text, err, missing = _gemini_generate(model, prompt, max_tokens,
                                              api_key)
        if text:
            log.info(f"Gemini {model} başarılı")
            return text
        errors.append(err)
        all_missing = all_missing and missing

    if all_missing:
        log.warning("Gemini: listedeki modeller kaldırılmış, "
                    "güncel liste deneniyor")
        for model in _discover_gemini_models(api_key, set(tried)):
            text, err, _ = _gemini_generate(model, prompt, max_tokens,
                                            api_key)
            if text:
                log.info(f"Gemini {model} başarılı (otomatik seçildi — "
                         f"GEMINI_MODELS'e eklemeyi düşün)")
                return text
            errors.append(err)
    raise RuntimeError("Gemini tüm modeller başarısız: " + " | ".join(errors))


def _discover_groq_models(api_key: str, exclude: set) -> list:
    """Groq'un güncel model listesinden genel amaçlı metin modelleri seçer."""
    import requests
    try:
        r = requests.get(f"{GROQ_BASE}/models", timeout=20,
                         headers={"Authorization": f"Bearer {api_key}"})
        if r.status_code != 200:
            log.warning(f"Groq model listesi alınamadı: HTTP {r.status_code}")
            return []
        ids = [m.get("id", "") for m in r.json().get("data", [])
               if m.get("active", True)]
        ids = [i for i in ids if i and i not in exclude
               and not any(w in i.lower() for w in _SKIP_WORDS)]
        # Tercih sırası: gpt-oss, llama, qwen, kimi, sonra diğerleri
        prefs = ("gpt-oss", "llama", "qwen", "kimi")
        ids.sort(key=lambda i: next((n for n, p in enumerate(prefs)
                                     if p in i.lower()), len(prefs)))
        log.info(f"Groq otomatik model adayları: {ids[:3]}")
        return ids[:2]
    except Exception as e:
        log.warning(f"Groq model listesi hatası: {type(e).__name__}")
        return []


def _groq_generate(model: str, prompt: str, max_tokens: int, api_key: str):
    """Tek bir Groq modelini dener. (metin, hata, model_yok) döner."""
    import requests
    payload = {
        "model": model,
        "messages": [
            {"role": "system",
             "content": "Sadece geçerli JSON döndür, başka hiçbir şey yazma."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.85,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if "gpt-oss" in model:
        # gpt-oss akıl yürütme token'ları da max_tokens'tan yer
        payload["reasoning_effort"] = "low"
        payload["max_tokens"] = max_tokens * 2
    try:
        r = requests.post(f"{GROQ_BASE}/chat/completions", json=payload,
                          timeout=60,
                          headers={"Authorization": f"Bearer {api_key}",
                                   "Content-Type": "application/json"})
    except Exception as e:
        return None, f"{model}: {type(e).__name__}: {str(e)[:150]}", False
    if r.status_code != 200:
        missing = r.status_code == 404 or "model_not_found" in r.text
        return None, f"{model}: HTTP {r.status_code}: {r.text[:150]}", missing
    choice = r.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        return None, f"{model}: max_tokens'ta kesildi", False
    text = choice["message"].get("content") or ""
    if not text:
        return None, f"{model}: boş metin", False
    return text, None, False


def _call_groq(prompt: str, max_tokens: int) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY yok")
    log.info("  → Groq deneniyor...")

    # Eski tek-model değişkeni de desteklenir
    default = _env_list("GROQ_MODEL", DEFAULT_GROQ_MODELS)
    errors = []
    tried = []
    all_missing = True
    for model in _env_list("GROQ_MODELS", default):
        tried.append(model)
        text, err, missing = _groq_generate(model, prompt, max_tokens,
                                            api_key)
        if text:
            log.info(f"Groq {model} başarılı")
            return text
        errors.append(err)
        all_missing = all_missing and missing

    if all_missing:
        log.warning("Groq: listedeki modeller kaldırılmış, "
                    "güncel liste deneniyor")
        for model in _discover_groq_models(api_key, set(tried)):
            text, err, _ = _groq_generate(model, prompt, max_tokens, api_key)
            if text:
                log.info(f"Groq {model} başarılı (otomatik seçildi — "
                         f"GROQ_MODELS'e eklemeyi düşün)")
                return text
            errors.append(err)
    raise RuntimeError("Groq tüm modeller başarısız: " + " | ".join(errors))
