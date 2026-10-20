"""
Gök olayları takvimi (Instagram içerikleri için)
────────────────────────────────────────────────
Kod ile hesaplanır (ephem kütüphanesi), dış servis yok:
  • Yeni Ay / Dolunay (hangi burçta) ve tutulmalar (yaklaşık)
  • Güneş'in burç değiştirmesi (yeni burç sezonu)
  • Merkür, Venüs, Mars retrosu başlangıcı ve bitişi (düzelme)

Tropikal zodyak, tarihe göre ekliptik (epoch=tarih) kullanılır.
"""

import math
from datetime import datetime, timedelta, timezone

import ephem

SIGNS = ["Koç", "Boğa", "İkizler", "Yengeç", "Aslan", "Başak",
         "Terazi", "Akrep", "Yay", "Oğlak", "Kova", "Balık"]
PLANETS = {"Merkür": ephem.Mercury, "Venüs": ephem.Venus,
           "Mars": ephem.Mars}


def _ecl(body_cls, when):
    b = body_cls(when)
    e = ephem.Ecliptic(b, epoch=when)
    return math.degrees(e.lon) % 360, math.degrees(e.lat)


def sign_of(lon: float) -> str:
    return SIGNS[int(lon // 30) % 12]


def _to_dt(d) -> datetime:
    return ephem.Date(d).datetime().replace(tzinfo=timezone.utc)


def _moons(start, end):
    out = []
    for kind, fn, emoji in (("yeniay", ephem.next_new_moon, "🌑"),
                            ("dolunay", ephem.next_full_moon, "🌕")):
        d = fn(start)
        while d < end:
            lon, lat = _ecl(ephem.Moon, d)
            sign = sign_of(lon)
            # Ay düğüme yakınsa tutulma olur (yaklaşık eşik)
            eclipse = abs(lat) < (1.5 if kind == "yeniay" else 1.0)
            if kind == "yeniay":
                name = "Güneş Tutulması" if eclipse else "Yeni Ay"
            else:
                name = "Ay Tutulması" if eclipse else "Dolunay"
            out.append({"type": "tutulma" if eclipse else kind,
                        "when": _to_dt(d), "sign": sign,
                        "title": f"{name} — {sign} burcunda",
                        "emoji": "🌘" if eclipse else emoji})
            d = fn(d + 1)
    return out


def _sun_ingress(start, end):
    out = []
    d = start
    prev = sign_of(_ecl(ephem.Sun, d)[0])
    while d < end:
        nxt = ephem.Date(d + 1)
        cur = sign_of(_ecl(ephem.Sun, nxt)[0])
        if cur != prev:
            lo, hi = float(d), float(nxt)
            for _ in range(30):                    # saniye hassasiyeti
                mid = (lo + hi) / 2
                if sign_of(_ecl(ephem.Sun, mid)[0]) == prev:
                    lo = mid
                else:
                    hi = mid
            out.append({"type": "sezon", "when": _to_dt(hi), "sign": cur,
                        "title": f"Güneş {cur} burcuna geçiyor "
                                 f"({cur} sezonu başlıyor)", "emoji": "☀️"})
            prev = cur
        d = nxt
    return out


def _retrogrades(start, end):
    out = []
    for name, cls in PLANETS.items():
        def motion(t):
            a = _ecl(cls, t - 0.5)[0]
            b = _ecl(cls, t + 0.5)[0]
            return ((b - a + 180) % 360) - 180    # günlük hareket (derece)
        d = start
        prev = motion(d)
        while d < end:
            nxt = ephem.Date(d + 1)
            cur = motion(nxt)
            if (prev > 0) != (cur > 0):
                lon = _ecl(cls, nxt)[0]
                retro = cur < 0
                out.append({
                    "type": "retro" if retro else "duzelme",
                    "when": _to_dt(nxt), "sign": sign_of(lon),
                    "planet": name,
                    "title": (f"{name} retrosu başlıyor — {sign_of(lon)} "
                              f"burcunda" if retro else
                              f"{name} düzeliyor (retro bitiyor) — "
                              f"{sign_of(lon)} burcunda"),
                    "emoji": "☿" if name == "Merkür" else "🪐"})
            prev = cur
            d = nxt
    return out


def events_between(start: datetime, end: datetime) -> list:
    """[start, end) aralığındaki gök olayları, zamana göre sıralı."""
    s = ephem.Date(start.astimezone(timezone.utc).replace(tzinfo=None))
    e = ephem.Date(end.astimezone(timezone.utc).replace(tzinfo=None))
    evs = _moons(s, e) + _sun_ingress(s, e) + _retrogrades(s, e)
    return sorted(evs, key=lambda x: x["when"])


def upcoming(days: int = 30) -> list:
    now = datetime.now(timezone.utc)
    return events_between(now, now + timedelta(days=days))
