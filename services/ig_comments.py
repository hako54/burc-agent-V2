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


_ASCII = str.maketrans("çğıöşüâîû", "cgiosuaiu")
# Burç kökleri (ünsüz yumuşaması dahil: akrebim, balığım, oğlağım)
_STEMS = {
    "koc": "koc", "boga": "boga", "ikizler": "ikizler", "yengec": "yengec",
    "aslan": "aslan", "basak": "basak", "terazi": "terazi", "akrep": "akrep",
    "akreb": "akrep", "yay": "yay", "oglak": "oglak", "oglag": "oglak",
    "kova": "kova", "balik": "balik", "balig": "balik",
}
_SUFFIXES = ("", "im", "um", "yim", "yum", "iz", "uz", "yiz", "yuz", "in",
             "un", "yin", "yun", "dir", "tir", "dur", "tur", "burcu",
             "burcuyum", "burcum", "burcuyuz", "luyum", "liyim", "cuyum",
             "ciyim", "cum", "cim", "yimdir", "yumdur")


def _sign_word(w: str):
    """'Kovayım', 'akrebim', 'koçum', 'balığız', "terazi'yim" → burç."""
    from zodiac import normalize_sign
    from services.tr_locale import tr_lower
    key = normalize_sign(w)
    if key:
        return key
    a = tr_lower(w).replace("'", "").replace("’", "").translate(_ASCII)
    for stem, k in _STEMS.items():
        if a.startswith(stem) and a[len(stem):] in _SUFFIXES:
            return k
    return None


def _sign_in(text: str):
    import re
    # Yalnızca harf grupları (emoji/noktalama bitişik olsa da: "Kova🤲❤️")
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû'’]+", text or "")
    if not 1 <= len(words) <= 4:
        return None
    for w in words:
        key = _sign_word(w)
        if key:
            return key
    return None


def _sign_message(key: str, st: dict) -> str:
    """Burca bugüne özel 2-3 cümlelik mesaj (günde bir kez üretilir)."""
    from zodiac import get_sign
    from services.tr_locale import tr_date, now_local
    today = now_local().strftime("%Y-%m-%d")
    cache = st.setdefault("sign_msgs", {})
    if (cache.get(key, {}).get("date") == today
            and cache[key].get("v") == 5):
        return cache[key]["text"]
    info = get_sign(key)
    from services.content import call_llm_with_fallback
    text, _ = call_llm_with_fallback(
        f"""Sen "Günlük Burç" Instagram hesabının astroloğusun. Bir takipçin
bir videonun altına sadece burcunu yazdı: {info['name']}. Ona yorumun altında
cevap olarak {tr_date()} günü için {info['name']} burcuna özel EN FAZLA 2 kısa
cümlelik (toplam 25 kelimeyi geçmesin), net, NEŞELİ ve MOTİVE EDİCİ bir
astroloji yorumu yaz: bugün onu bekleyen güzel bir şeyi ve içindeki gücü
hatırlat; okuyan gülümsesin, kendini iyi hissetsin. Uyarı, korkutma ya da
olumsuzluk yok. 1-2 emoji kullan.
Kurallar: takipçiye "sen" diye hitap et; teşekkür etme; kendinden, hesaptan
ya da yapay zekâdan bahsetme; takipçinin ağzından yazma. Sonuna "Günlük
yorumun için takipte kal 💫" ekle. Sadece cevap metnini yaz.""",
        max_tokens=300)
    text = text.strip().strip('"')
    try:
        from services.tr_spell import fix_turkish
        text = fix_turkish([text])[0] or text
    except Exception as e:
        log.warning(f"İmla kontrolü yapılamadı: {e}")
    cache[key] = {"date": today, "text": text, "v": 5}
    return text


_NOT_NAMES = {"ya", "allah", "allahım", "allahim", "amin", "amen",
              "elhamdulillah", "maşallah", "masallah", "inşallah", "insallah",
              "rabbim", "şükür", "sukur", "harika", "süper", "super", "teşekkürler",
              "tesekkurler", "çok", "cok", "güzel", "guzel", "bravo", "evet"}


def _looks_like_name(comment: str) -> bool:
    """İsim yorumu kısa olur: 'Hakan', 'benim adım Ayşe'. Uzun ya da dua/övgü
    içeren yorumlara isim analizi yazılmaz."""
    import re
    from services.tr_locale import tr_lower
    t = re.sub(r"(?i)\b(benim|adım|adim|ismim|ben)\b", " ", comment or "")
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]{2,20}", t)
    if not 1 <= len(words) <= 2:
        return False
    return not any(tr_lower(w) in _NOT_NAMES for w in words)


def _general_reply(comment: str) -> str:
    """Burç/isim dışındaki yorumlara kısa, samimi teşekkür (yorumun
    içeriğine uygun). Spam, reklam, link ya da kaba yorumlara cevap yok."""
    if os.environ.get("IG_COMMENT_THANKS", "1") in ("0", "false"):
        return None
    text = (comment or "").strip()
    if not text or "http" in text.lower() or "www." in text.lower():
        return None
    from services.content import call_llm_with_fallback
    try:
        out, _ = call_llm_with_fallback(
            f"""Bir burç/astroloji Instagram hesabının videosuna şu yorum
yapıldı: "{text[:300]}"
Hesap adına yorumun altına yazılacak KISA bir cevap yaz: en fazla 8 kelime,
çok sıcak, neşeli ve içten, yoruma uygun (emoji/övgü → teşekkür; dua → "Amin 🤲" tarzı;
soru → kısa, nazik cevap). 1 emoji kullanabilirsin. Kendinden ya da yapay
zekâdan bahsetme. Yorum spam, reklam, hakaret, kaba ya da alakasızsa
sadece SKIP yaz. Sadece cevap metnini yaz.""", max_tokens=60)
    except Exception as e:
        log.warning(f"Teşekkür cevabı üretilemedi: {e}")
        return None
    out = out.strip().strip('"')
    if not out or "SKIP" in out.upper() or len(out) > 120:
        return None
    return out


def _reply_text(comment: str, st: dict):
    """(metin, tür) döner; tür: "analiz" (DM'e gider) ya da "tesekkur"
    (yalnızca yorumun altına)."""
    key = _sign_in(comment)
    if key:
        return _sign_message(key, st), "analiz"
    if not _looks_like_name(comment):
        return _general_reply(comment), "tesekkur"
    from services.name_analysis import analyze, NOT_A_NAME
    text = analyze(comment, strict=True)
    if text == NOT_A_NAME:
        return _general_reply(comment), "tesekkur"
    return text, "analiz"


def _card_text(text: str) -> str:
    """Kart için takip çağrısı cümlesini çıkarır."""
    import re
    out = re.sub(r"\s*(Günlük\s+(burç\s+)?yorum\w*\s+için\s+)?takipte\s+"
                 r"kal\w*[\s.!💫✨]*$", "", text, flags=re.I).strip()
    return out or text


def _card_title(comment: str) -> str:
    from zodiac import get_sign
    key = _sign_in(comment)
    if key:
        info = get_sign(key)
        return f"{info['symbol']} {info['name']}"
    from services.name_analysis import extract_name
    return extract_name(comment) or "Sana Özel"


def _send_dm(instagram, uid: str, cid: str, text: str, comment: str,
             handle: str) -> bool:
    """Önce hikâyede paylaşılabilir görsel kart, olmazsa yazı gönderir.
    IG_COMMENT_CARD=0 ise yalnızca yazı."""
    if os.environ.get("IG_COMMENT_CARD", "1") not in ("0", "false"):
        try:
            from services.story_card import make_card
            qd = instagram._queue_dir()
            for old in qd.glob("card_*.jpg"):
                if time.time() - old.stat().st_mtime > 3 * 86400:
                    old.unlink(missing_ok=True)
            name = f"card_{cid}.jpg"
            make_card(_card_title(comment), _card_text(text),
                      str(qd / name), handle=handle)
            url = instagram._public_url(name)
            for attempt in range(3):
                try:
                    instagram.send_private_reply(uid, cid, image_url=url)
                    log.info(f"🖼️ Hikâye kartı DM ile gönderildi: {cid}")
                    return True
                except Exception as e:
                    if attempt == 2:
                        raise
                    log.info(f"Kart DM denemesi {attempt + 1} başarısız "
                             f"({e}); tekrar deneniyor")
                    time.sleep(8)
        except Exception as e:
            log.warning(f"Kart DM gönderilemedi, yazı deneniyor: {e}")
    try:
        instagram.send_private_reply(uid, cid, text)
        return True
    except Exception as e:
        log.warning(f"DM gönderilemedi, yoruma yazılıyor: {e}")
        return False


_THANKS = [
    "Teşekkürler 💜 Sana özel kartın DM'inde, hikâyende paylaşmayı unutma ✨",
    "Yorumun için teşekkürler 🌙 Sana özel mesajın DM kutunda 💌",
    "Çok teşekkürler 💫 DM'ine güzel bir sürpriz bıraktım ✨",
]


def _thanks() -> str:
    import random
    return random.choice(_THANKS)


def _short(text: str, max_sentences: int = 2) -> str:
    """Herkese açık cevap kısa olsun: ilk 2 cümle (+ takip çağrısı)."""
    import re
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    out = " ".join(parts[:max_sentences]).strip()
    if "takipte" not in out.lower():
        out += " 💫"
    return out


def _alert_once(st: dict, msg: str) -> None:
    if time.time() - st.get("last_alert", 0) < 6 * 3600:
        return
    st["last_alert"] = time.time()
    try:
        from telegram_bot import send as tg_send
        tg_send(msg)
    except Exception:
        pass


def _all_comments(instagram, media_id: str, fields: str) -> list:
    """Bir gönderinin tüm yorumları (50'şerlik sayfaları takip eder)."""
    out, after = [], None
    for _ in range(20):
        params = {"fields": fields, "limit": 50}
        if after:
            params["after"] = after
        r = instagram._api("GET", f"{media_id}/comments", **params)
        out += r.get("data", [])
        after = ((r.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or not (r.get("paging") or {}).get("next"):
            break
    return out


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
        # Son 7 günün tüm gönderileri (günde ~8 gönderi); yalnızca yorum
        # sayısı değişenlerin yorumları okunur (API çağrısı tasarrufu)
        media = instagram._api("GET", f"{uid}/media",
                               fields="id,timestamp,comments_count",
                               limit=80).get("data", [])
        done = set(st["done"])
        counts = st.setdefault("counts", {})
        for m in media:
            ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
            if ts < since:
                continue
            n = m.get("comments_count", 0)
            if not n or counts.get(m["id"]) == n:
                continue
            comments = _all_comments(instagram, m["id"], "id,text,username,timestamp")
            for c in comments:
                if replied >= MAX_PER_RUN:
                    break
                cid = c["id"]
                if cid in done or c.get("username") == my_name:
                    continue
                text, kind = _reply_text(c.get("text", ""), st)
                if text:
                    who = c.get("username")
                    sent_dm = False
                    if kind == "analiz" and _dm_enabled():
                        sent_dm = _send_dm(instagram, uid, cid, text,
                                           c.get("text", ""), my_name)
                    public = (_thanks() if sent_dm
                              else text if kind == "tesekkur" else _short(text))
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
            if replied < MAX_PER_RUN:
                counts[m["id"]] = n
                _save_state(st)
    except Exception as e:
        log.warning(f"Yorum cevaplama hatası: {e}")
        _alert_once(st, f"⚠️ Instagram yorumlarına cevap verilemedi: "
                        f"{str(e)[:250]}")
        _save_state(st)
    finally:
        _lock.release()
    return {"replied": replied, "skipped": skipped}


def overview(days: int = 3) -> list:
    """Son gönderilerdeki yorumlar ve cevap durumu (kontrol için)."""
    from services import instagram
    st = _load_state()
    done = set(st["done"])
    me = instagram.account_info()
    uid, my_name = str(me.get("user_id")), me.get("username", "")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    media = instagram._api("GET", f"{uid}/media", fields="id,timestamp,caption",
                           limit=25).get("data", [])
    for m in media:
        ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if ts < since:
            continue
        cs = _all_comments(instagram, m["id"], "id,text,username,timestamp,replies{id,username,text}")
        for c in cs:
            reps = (c.get("replies") or {}).get("data", [])
            out.append({
                "id": c["id"], "media_id": m["id"],
                "post": (m.get("caption") or "")[:40],
                "user": c.get("username"), "text": (c.get("text") or "")[:120],
                "mine": c.get("username") == my_name,
                "processed": c["id"] in done,
                "my_reply_id": next((r.get("id") for r in reps
                                     if r.get("username") == my_name), None),
                "my_reply": next((r.get("text", "")[:160] for r in reps
                                  if r.get("username") == my_name), None),
                "type": ("burç" if _sign_in(c.get("text", "")) else "?")})
    return out


def forget(comment_id: str) -> bool:
    """Yorumu 'işlendi' listesinden çıkarır (bir sonraki turda yeniden
    cevaplanır)."""
    st = _load_state()
    had = comment_id in st["done"]
    st["done"] = [c for c in st["done"] if c != comment_id]
    st["counts"] = {}  # gönderiler yeniden taransın
    _save_state(st)
    return had


def _old_sign_in(text: str):
    """Eski (ekleri tanımayan) burç tanıma — yanlış cevaplananları bulmak
    için."""
    from zodiac import normalize_sign
    words = [w.strip(".,!?♈♉♊♋♌♍♎♏♐♑♒♓✨💫❤️ ") for w in text.split()]
    if not 1 <= len(words) <= 4:
        return None
    for w in words:
        if normalize_sign(w):
            return normalize_sign(w)
    return None


def fix_misread_signs(dry_run: bool = False) -> list:
    """Burcunu ekli yazdığı için ('Kovayım') isim sanılıp isim analizi
    gönderilen yorumlara yorumun altından özür + doğru burç mesajı yazar.
    (Aynı yoruma ikinci DM gönderilemez; Instagram tek DM'e izin verir.)"""
    from services import instagram
    from zodiac import get_sign
    st = _load_state()
    fixed = set(st.setdefault("fixed", []))
    done = set(st["done"])
    me = instagram.account_info()
    uid, my_name = str(me.get("user_id")), me.get("username", "")
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    media = instagram._api("GET", f"{uid}/media",
                           fields="id,timestamp,comments_count",
                           limit=80).get("data", [])
    out = []
    for m in media:
        ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if ts < since or not m.get("comments_count"):
            continue
        cs = _all_comments(instagram, m["id"], "id,text,username")
        for c in cs:
            cid, text = c["id"], c.get("text", "")
            if (c.get("username") == my_name or cid in fixed
                    or cid not in done):
                continue
            key = _sign_in(text)
            # Yalnızca eskiden isim analizine giden yorumlar
            if not key or _old_sign_in(text) or not _looks_like_name(text):
                continue
            name = get_sign(key)["name"]
            msg = (f"Özür dileriz 🙏 Burcunu yanlışlıkla isim sandık, DM'deki "
                   f"mesajı dikkate alma! {name} için bugünün mesajı: "
                   f"{_sign_message(key, st)}")
            out.append({"comment": text, "reply": msg})
            if dry_run:
                continue
            instagram._api("POST", f"{cid}/replies", message=msg[:1000])
            st["fixed"].append(cid)
            _save_state(st)
            log.info(f"🙏 Yanlış cevap düzeltildi: {cid} ({text[:30]})")
    return out
