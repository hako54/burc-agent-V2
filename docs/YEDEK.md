# Yedekleme ve yedek üretim

## 1. Günlük şifreli yedek

Her gece 04:10'da (İstanbul) Railway volume'ündeki kalıcı veriler (kanal
ayarları, geçmiş, Instagram token'ı, yorum durumu) şifrelenip Telegram bot
sohbetine `burc_yedek_YYYYMMDD.enc` olarak gönderilir. Videolar ve astrolog
klip önbelleği yedeğe girmez.

- Şifre: Railway'de `BACKUP_KEY` (yoksa `PANEL_PASSWORD`).
- Hemen yedek almak: `POST /api/backup/run`
- Geri yükleme (yeni sunucuda):
  ```bash
  BACKUP_KEY=... python scripts/restore_backup.py burc_yedek_YYYYMMDD.enc data
  ```
  Açılan `data` klasörü yeni sunucuda `DATA_DIR` olur.

## 2. GitHub Actions yedek üretim

`.github/workflows/fallback-burc.yml` her gün 07:15 ve 10:40'ta (İstanbul)
YouTube kanalına bakar. Bugünün burçlarından en az biri yüklenmişse hiçbir
şey yapmaz (~1 dk). Hiçbiri yoksa (Railway çökmüş) videoları GitHub'da
üretip YouTube'a hemen yükler ve Telegram'a bildirir. Bu modda astrolog
klibi (HeyGen) ve Instagram yoktur.

Elle çalıştırmak: GitHub → Actions → "Yedek burç üretimi" → Run workflow
(`dry_run`: sadece kontrol, `force`: yine de üret).

### Gerekli GitHub Secrets

GitHub → repo → Settings → Secrets and variables → Actions → New repository
secret. Değerler Railway'deki değişkenlerle aynıdır:

| Secret | Zorunlu |
|---|---|
| `TOKEN_BURC` | evet |
| `CREDENTIALS_BURC` | evet |
| `ANTHROPIC_API_KEY` | evet (veya GEMINI/GROQ) |
| `ELEVENLABS_API_KEY` | evet |
| `ELEVENLABS_VOICE_ID` | evet |
| `PEXELS_API_KEY` | evet |
| `TELEGRAM_BOT_TOKEN` | önerilir |
| `TELEGRAM_CHAT_ID` | önerilir |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `PIXABAY_API_KEY` | isteğe bağlı |

Kanal ayarları (ses vb.) `scripts/fallback_channels.json` kopyasından gelir;
Railway'de kanal sesi değişirse bu dosya da güncellenmeli.
