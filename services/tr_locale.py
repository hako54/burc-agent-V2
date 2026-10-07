"""
Türkçe yerel ayar yardımcıları.

- now_local(): TIMEZONE env'ine göre şu anki zaman (sunucu UTC olsa bile)
- tr_date(): "07 Ekim 2026" — strftime("%B") İngilizce ay verdiği için
- tr_upper()/tr_lower(): Python'un i/İ ve ı/I dönüşümü Türkçe'ye uymaz
"""

import os
from datetime import datetime

import pytz

TR_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


def now_local() -> datetime:
    tz = pytz.timezone(os.environ.get("TIMEZONE", "Europe/Istanbul"))
    return datetime.now(tz)


def tr_date(dt: datetime = None) -> str:
    dt = dt or now_local()
    return f"{dt.day:02d} {TR_MONTHS[dt.month - 1]} {dt.year}"


def tr_upper(text: str) -> str:
    return text.replace("i", "İ").replace("ı", "I").upper()


def tr_lower(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower()
