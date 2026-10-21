"""
Şifreli günlük yedeği açar.

Kullanım:
    python scripts/restore_backup.py burc_yedek_YYYYMMDD.enc hedef_klasör
Şifre BACKUP_KEY (yoksa PANEL_PASSWORD) ortam değişkeninden okunur,
yoksa sorulur. Açılan klasör yeni sunucuda DATA_DIR olarak kullanılır.
"""

import os
import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.backup import restore_backup  # noqa: E402


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    password = (os.environ.get("BACKUP_KEY") or os.environ.get("PANEL_PASSWORD")
                or getpass.getpass("Yedek şifresi: "))
    names = restore_backup(Path(sys.argv[1]).read_bytes(), sys.argv[2],
                           password)
    print(f"✅ {len(names)} dosya açıldı → {sys.argv[2]}")


if __name__ == "__main__":
    main()
