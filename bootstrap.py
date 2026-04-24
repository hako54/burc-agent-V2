"""
Bootstrap — Uygulama başlangıcında ortam hazırlığı.

Railway gibi bulut platformlarında dosya sistemi sınırlıdır. OAuth
credentials (credentials_burc.json, token_burc.json) environment variable
olarak saklanır ve uygulama başlarken dosyaya yazılır.

Ayrıca gerekli dizinleri oluşturur ve logging yapılandırması sağlar.
"""

import os
import base64
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _decode_env_to_file(env_key: str, file_path: str) -> bool:
    """Environment variable'dan (base64 veya düz JSON) dosya oluşturur."""
    value = os.environ.get(env_key)
    if not value:
        return False

    # Dosya zaten varsa üzerine yazma (geliştirmede lokal dosya öncelikli)
    if os.path.exists(file_path):
        return False

    try:
        # Önce base64 decode dene
        decoded = base64.b64decode(value).decode("utf-8")
        # Geçerli JSON mu kontrol et
        json.loads(decoded)
        content = decoded
    except Exception:
        # Düz JSON string olabilir
        try:
            json.loads(value)
            content = value
        except Exception as e:
            log.error(f"{env_key} parse edilemedi: {e}")
            return False

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info(f"✅ {file_path} oluşturuldu ({env_key})")
    return True


def setup_credentials():
    """YouTube OAuth dosyalarını env variable'lardan oluşturur."""
    _decode_env_to_file("CREDENTIALS_BURC", "credentials_burc.json")
    _decode_env_to_file("TOKEN_BURC", "token_burc.json")


def setup_directories():
    """Gerekli çalışma dizinlerini oluşturur."""
    # DATA_DIR ve OUTPUT_DIR env var'dan gelebilir (Railway Volume için)
    data_dir = os.environ.get("DATA_DIR", "data")
    output_dir = os.environ.get("OUTPUT_DIR", "output")
    dirs = [data_dir, output_dir, "static/preview", "shortmusic"]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)


def setup_logging():
    """Temel logging yapılandırması."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Gürültülü kütüphaneleri sustur
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)


def setup_all():
    """Tüm bootstrap adımları."""
    # .env dosyası varsa yükle (lokal geliştirme)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    setup_logging()
    setup_directories()
    setup_credentials()
