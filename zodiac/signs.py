"""
12 Burç Meta Bilgisi
Tüm sistem için tek kaynak. Her burç için sembol, renk, element, görsel
arama terimleri ve takma adlar.
"""

ZODIAC_SIGNS = {
    "koc": {
        "name": "Koç", "symbol": "♈", "emoji": "🐏",
        "element": "Ateş", "dates": "21 Mart - 19 Nisan",
        "ruler": "Mars", "color": "#dc2626", "bg": "#2a0a0a",
        "traits": "cesur, atılgan, lider, enerjik",
        "en_name": "aries",
        "visual_queries": [
            "fire flames dramatic",
            "red sunrise mountain",
            "aries zodiac fire",
        ],
    },
    "boga": {
        "name": "Boğa", "symbol": "♉", "emoji": "🐂",
        "element": "Toprak", "dates": "20 Nisan - 20 Mayıs",
        "ruler": "Venüs", "color": "#15803d", "bg": "#0a1f10",
        "traits": "sabırlı, kararlı, güvenilir, estetik",
        "en_name": "taurus",
        "visual_queries": [
            "green earth nature",
            "taurus bull field",
            "emerald forest dawn",
        ],
    },
    "ikizler": {
        "name": "İkizler", "symbol": "♊", "emoji": "👯",
        "element": "Hava", "dates": "21 Mayıs - 20 Haziran",
        "ruler": "Merkür", "color": "#eab308", "bg": "#1f1a05",
        "traits": "meraklı, iletişimci, hızlı, çok yönlü",
        "en_name": "gemini",
        "visual_queries": [
            "yellow sky clouds wind",
            "gemini twins stars",
            "golden light air",
        ],
    },
    "yengec": {
        "name": "Yengeç", "symbol": "♋", "emoji": "🦀",
        "element": "Su", "dates": "21 Haziran - 22 Temmuz",
        "ruler": "Ay", "color": "#c0c0c0", "bg": "#0a1220",
        "traits": "duygusal, koruyucu, sezgisel, aileci",
        "en_name": "cancer",
        "visual_queries": [
            "silver moon ocean",
            "cancer zodiac water",
            "moonlight sea waves",
        ],
    },
    "aslan": {
        "name": "Aslan", "symbol": "♌", "emoji": "🦁",
        "element": "Ateş", "dates": "23 Temmuz - 22 Ağustos",
        "ruler": "Güneş", "color": "#f59e0b", "bg": "#1f1005",
        "traits": "gururlu, cömert, yaratıcı, lider",
        "en_name": "leo",
        "visual_queries": [
            "golden lion sun",
            "leo zodiac fire",
            "royal gold dramatic light",
        ],
    },
    "basak": {
        "name": "Başak", "symbol": "♍", "emoji": "🌾",
        "element": "Toprak", "dates": "23 Ağustos - 22 Eylül",
        "ruler": "Merkür", "color": "#84cc16", "bg": "#0f1a05",
        "traits": "titiz, analitik, pratik, mükemmeliyetçi",
        "en_name": "virgo",
        "visual_queries": [
            "wheat field harvest",
            "virgo zodiac earth",
            "green nature detail",
        ],
    },
    "terazi": {
        "name": "Terazi", "symbol": "♎", "emoji": "⚖️",
        "element": "Hava", "dates": "23 Eylül - 22 Ekim",
        "ruler": "Venüs", "color": "#ec4899", "bg": "#1f0a18",
        "traits": "dengeli, adil, estetik, uyumlu",
        "en_name": "libra",
        "visual_queries": [
            "pink sky sunset balance",
            "libra zodiac air",
            "pastel clouds harmony",
        ],
    },
    "akrep": {
        "name": "Akrep", "symbol": "♏", "emoji": "🦂",
        "element": "Su", "dates": "23 Ekim - 21 Kasım",
        "ruler": "Plüton", "color": "#7c3aed", "bg": "#15081f",
        "traits": "tutkulu, gizemli, yoğun, güçlü",
        "en_name": "scorpio",
        "visual_queries": [
            "dark purple mystery",
            "scorpio zodiac night",
            "deep water shadow",
        ],
    },
    "yay": {
        "name": "Yay", "symbol": "♐", "emoji": "🏹",
        "element": "Ateş", "dates": "22 Kasım - 21 Aralık",
        "ruler": "Jüpiter", "color": "#a855f7", "bg": "#15081f",
        "traits": "özgür, iyimser, maceracı, felsefi",
        "en_name": "sagittarius",
        "visual_queries": [
            "purple mountain adventure",
            "sagittarius zodiac arrow",
            "violet sky journey",
        ],
    },
    "oglak": {
        "name": "Oğlak", "symbol": "♑", "emoji": "🐐",
        "element": "Toprak", "dates": "22 Aralık - 19 Ocak",
        "ruler": "Satürn", "color": "#64748b", "bg": "#0a0f1a",
        "traits": "disiplinli, sorumlu, hırslı, sabırlı",
        "en_name": "capricorn",
        "visual_queries": [
            "gray mountain peak",
            "capricorn zodiac stone",
            "snowy summit climb",
        ],
    },
    "kova": {
        "name": "Kova", "symbol": "♒", "emoji": "🏺",
        "element": "Hava", "dates": "20 Ocak - 18 Şubat",
        "ruler": "Uranüs", "color": "#06b6d4", "bg": "#05181f",
        "traits": "özgün, yenilikçi, bağımsız, vizyoner",
        "en_name": "aquarius",
        "visual_queries": [
            "cyan water flow",
            "aquarius zodiac futuristic",
            "blue electric sky",
        ],
    },
    "balik": {
        "name": "Balık", "symbol": "♓", "emoji": "🐟",
        "element": "Su", "dates": "19 Şubat - 20 Mart",
        "ruler": "Neptün", "color": "#0ea5e9", "bg": "#05101f",
        "traits": "hayalperest, sezgisel, duyarlı, sanatsal",
        "en_name": "pisces",
        "visual_queries": [
            "deep ocean blue dream",
            "pisces zodiac water",
            "underwater mystical light",
        ],
    },
}


# Kullanıcı girdisi normalizasyonu
# Türkçe aksanlı, aksansız, İngilizce ve büyük/küçük harf farklılıklarını tolere eder
SIGN_ALIASES = {
    # Türkçe
    "koç": "koc", "koc": "koc",
    "boğa": "boga", "boga": "boga",
    "ikizler": "ikizler",
    "yengeç": "yengec", "yengec": "yengec",
    "aslan": "aslan",
    "başak": "basak", "basak": "basak",
    "terazi": "terazi",
    "akrep": "akrep",
    "yay": "yay",
    "oğlak": "oglak", "oglak": "oglak",
    "kova": "kova",
    "balık": "balik", "balik": "balik",
    # İngilizce
    "aries": "koc", "taurus": "boga", "gemini": "ikizler",
    "cancer": "yengec", "leo": "aslan", "virgo": "basak",
    "libra": "terazi", "scorpio": "akrep", "sagittarius": "yay",
    "capricorn": "oglak", "aquarius": "kova", "pisces": "balik",
}


def normalize_sign(name: str) -> str | None:
    """Kullanıcı girdisini burç anahtarına çevirir. Tanımsızsa None döner."""
    if not name:
        return None
    return SIGN_ALIASES.get(name.lower().strip())


def get_sign(key: str) -> dict:
    """Verilen anahtar için burç meta bilgisini döner."""
    return ZODIAC_SIGNS[key]


def all_sign_keys() -> list:
    """12 burç anahtarını sabit sırayla döner."""
    return list(ZODIAC_SIGNS.keys())


# ── Gün aşırı rotasyon grupları ────────────────────────────────────
# YouTube günlük quota sınırı (~10.000/gün, 1 video ≈ 1.600 quota) nedeniyle
# 12 burcun hepsini aynı gün yayınlayamıyoruz. Bu yüzden iki gruba böldük:
GROUP_EVEN_DAYS = ["koc", "boga", "ikizler", "yengec", "aslan", "basak"]
GROUP_ODD_DAYS = ["terazi", "akrep", "yay", "oglak", "kova", "balik"]


def get_todays_group() -> list:
    """Bugünün günü tek mi çift mi → ona göre 6 burç döner.
    Çift günler (2, 4, 6...): Koç → Başak
    Tek günler (1, 3, 5...): Terazi → Balık"""
    from datetime import datetime
    day = datetime.now().day
    return GROUP_EVEN_DAYS if day % 2 == 0 else GROUP_ODD_DAYS

