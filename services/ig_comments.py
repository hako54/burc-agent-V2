"""
Instagram yorumlarına otomatik cevap
────────────────────────────────────
Son 7 günün gönderilerindeki yeni yorumları birkaç dakikada bir okur:
  • Yorum bir BURÇ adıysa ("Koç", "akrep ♏") → o burca bugüne özel kısa
    mesaj (burç başına günde bir kez üretilir, önbellekten)
  • Yorum bir İSİMse ("Ayşe", "benim adım ışıl") → isim analizi
  • Diğer yorumlar ("harika video") → cevap yok
Cevap yorumun altına "@kullanıcı ..." diye yazılır. IG_COMMENT_DM=1 ise
(Meta onayından sonra) analiz DM olarak gider, yoruma "DM'ine gönderdim
💌" yazılır.

IG_COMMENT_REPLY=0 ise kapalı. Her çalışmada en fazla 10 cevap.
"""

import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

MAX_PER_RUN = 10
LOOKBACK_DAYS = 7
_lock = threading.Lock()


def enabled() -> bool:
    from services import instagram
    return (instagram.enabled()
            and os.environ.get("IG_COMMENT_REPLY", "1") not in ("0", "false"))


def _dm_enabled() -> bool:
    """IG_COMMENT_DM=1: cevap DM olarak gider (Meta onayından sonra açılır).
    DM başarısız olursa cevap yine yorumun altına yazılır."""
    return os.environ.get("IG_COMMENT_DM", "0") in ("1", "true", "on")


def _state_file() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "ig_comments_state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except Exception:
        return {"done": [], "sign_msgs": {}, "last_alert": 0}


def _save_state(st: dict) -> None:
    st["done"] = st["done"][-5000:]
    _state_file().parent.mkdir(parents=True, exist_ok=True)
    tmp = _state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False))
    os.replace(tmp, _state_file())


def _sign_in(text: str):
    from zodiac import normalize_sign
    words = [w.strip(".,!?♈♉♊♋♌♍♎♏♐♑♒♓✨💫❤️ ") for w in text.split()]
    if not 1 <= len(words) <= 4:
        return None
    for w in words:
        key = normalize_sign(w)
        if key:
            return key
    return None


def _sign_message(key: str, st: dict) -> str:
    """Burca bugüne özel 2-3 cümlelik mesaj (günde bir kez üretilir)."""
    from zodiac import get_sign
    from services.tr_locale import tr_date, now_local
    today = now_local().strftime("%Y-%m-%d")
    cache = st.setdefault("sign_msgs", {})
    if cache.get(key, {}).get("date") == today:
        return cache[key]["text"]
    info = get_sign(key)
    from services.content import call_llm_with_fallback
    text, _ = call_llm_with_fallback(
        f"""Instagram'da {info['name']} burcundan biri yorum yaptı. Ona
yorumun altında cevap olarak bugüne ({tr_date()}) özel 2-3 kısa, sıcak,
somut cümle yaz ("sen" diliyle). Sonuna "Günlük yorumun için takipte
kal 💫" ekle. Sadece mesajı yaz.""", max_tokens=300)
    text = text.strip().strip('"')
    cache[key] = {"date": today, "text": text}
    return text


def _reply_text(comment: str, st: dict):
    key = _sign_in(comment)
    if key:
        return _sign_message(key, st)
    from services.name_analysis import analyze, NOT_A_NAME
    text = analyze(comment, strict=True)
    return None if text == NOT_A_NAME else text


def _alert_once(st: dict, msg: str) -> None:
    if time.time() - st.get("last_alert", 0) < 6 * 3600:
        return
    st["last_alert"] = time.time()
    try:
        from telegram_bot import send as tg_send
        tg_send(msg)
    except Exception:
        pass


def process_comments() -> dict:
    """Yeni yorumları cevaplar; {'replied': n, 'skipped': m} döner."""
    if not enabled():
        return {"replied": 0, "skipped": 0}
    from services import instagram
    if not _lock.acquire(blocking=False):
        return {"replied": 0, "skipped": 0}
    st = _load_state()
    replied = skipped = 0
    try:
        me = instagram.account_info()
        uid, my_name = str(me.get("user_id")), me.get("username", "")
        since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        media = instagram._api("GET", f"{uid}/media",
                               fields="id,timestamp", limit=15).get("data", [])
        done = set(st["done"])
        for m in media:
            ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
            if ts < since:
                continue
            comments = instagram._api(
                "GET", f"{m['id']}/comments",
                fields="id,text,username,timestamp", limit=50).get("data", [])
            for c in comments:
                if replied >= MAX_PER_RUN:
                    break
                cid = c["id"]
                if cid in done or c.get("username") == my_name:
                    continue
                text = _reply_text(c.get("text", ""), st)
                if text:
                    who = c.get("username")
                    sent_dm = False
                    if _dm_enabled():
                        try:
                            instagram.send_private_reply(uid, cid, text)
                            sent_dm = True
                        except Exception as e:
                            log.warning(f"DM gönderilemedi, yoruma "
                                        f"yazılıyor: {e}")
                    public = ("DM'ine gönderdim 💌 Kutunu kontrol et ✨"
                              if sent_dm else text)
                    msg = f"@{who} {public}" if who else public
                    instagram._api("POST", f"{cid}/replies",
                                   message=msg[:1000])
                    replied += 1
                    log.info(f"💬 Yoruma cevap verildi ({'DM' if sent_dm else 'yorum'}): {cid}")
                else:
                    skipped += 1
                st["done"].append(cid)
                done.add(cid)
                _save_state(st)
    except Exception as e:
        log.warning(f"Yorum cevaplama hatası: {e}")
        _alert_once(st, f"⚠️ Instagram yorumlarına cevap verilemedi: "
                        f"{str(e)[:250]}")
        _save_state(st)
    finally:
        _lock.release()
    return {"replied": replied, "skipped": skipped}
