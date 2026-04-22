# Burç Agent v2

Günlük burç yorumu üreten, video hazırlayıp YouTube'a yükleyen bulut tabanlı otomasyon sistemi.

## Özellikler

- 🔮 **12 burç için günlük yorum** — Claude / Gemini / Groq fallback zinciri
- 🎬 **Otomatik video üretimi** — 60 saniyelik dikey Shorts (aşk + kariyer + sağlık + şanslı sayı/renk)
- 🎙 **Çok katmanlı TTS** — ElevenLabs → Edge TTS → gTTS
- 📤 **YouTube otomatik yükleme** — OAuth 2.0 ile güvenli
- 🌐 **Web paneli** — her burca tıklayıp tek tek üretebilir veya "hepsi" diyebilirsin
- 🤖 **Telegram bot** — mobilden komut gönder, `/burc koç`
- ⏰ **Günlük otomatik cron** — her sabah 06:00'da 12 burç yayınlanır
- ☁️ **Railway'de çalışır** — bilgisayar açık tutmana gerek yok

## Mimari

```
┌─────────────────────────────────────────────┐
│  Kullanıcı                                  │
│  ├─ Web Panel (/)                           │
│  ├─ Telegram Bot (/burc aslan)              │
│  └─ Otomatik Cron (her sabah 06:00)         │
└────────────┬────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────┐
│  pipeline.py (orchestrator)                 │
└────────────┬────────────────────────────────┘
             ▼
    ┌────────┴────────┬────────┬─────────┐
    ▼                 ▼        ▼         ▼
 content.py      images.py  tts.py   video.py   youtube.py
 (Claude/        (Pixabay/  (gTTS)   (MoviePy   (OAuth
  Gemini/         Pexels)            +FFmpeg)    upload)
  Groq)
```

## Lokal Kurulum

```bash
# 1. Python 3.12 (Windows'ta 3.13 değil, 3.12 önerilir)
# https://www.python.org/downloads/release/python-31210/

# 2. Proje klasörüne gir
cd burc_v2

# 3. Paketleri yükle
pip install -r requirements.txt

# 4. .env oluştur
cp .env.example .env
# Notepad / editörde açıp API anahtarlarını doldur

# 5. YouTube OAuth credentials'i koy
# credentials_burc.json dosyasını kök klasöre kopyala
# (Google Cloud Console → APIs & Services → Credentials → OAuth Client)

# 6. İlk çalıştırma (OAuth akışı)
python -c "from services.youtube import get_youtube_service; get_youtube_service()"
# Tarayıcı açılır, Gmail ile giriş yap, izin ver
# token_burc.json otomatik oluşur

# 7. Uygulamayı başlat
python app.py
# http://localhost:5000 adresinde panel açılır
```

Telegram bot ve scheduler otomatik başlar. Telegram'dan `/yardim` yazarak test edebilirsin.

## Railway Deploy (Önerilen Yöntem)

### Ön koşul
- GitHub hesabı
- Railway.app hesabı (ücretsiz)

### Adım 1: Kodu GitHub'a yükle

```bash
cd burc_v2
git init
git add .
git commit -m "Initial commit"

# GitHub'da yeni repo oluştur (private yap!)
git remote add origin https://github.com/<kullanici>/burc-agent.git
git branch -M main
git push -u origin main
```

> ⚠️ **`.gitignore` dosyası `.env`, `credentials_burc.json`, `token_burc.json`'u zaten hariç tutar.** Bu dosyalar asla GitHub'a gitmez.

### Adım 2: Railway projesi oluştur

1. https://railway.app → **New Project** → **Deploy from GitHub repo**
2. `burc-agent` repo'sunu seç
3. Railway `Dockerfile`'ı otomatik algılar ve deploy başlar

### Adım 3: Environment variables ekle

Railway paneli → Proje → **Variables** sekmesi.

`.env.example`'daki tüm değişkenleri ekle:

| Variable | Değer |
|----------|-------|
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `GEMINI_API_KEY` | `AIzaSy...` |
| `GROQ_API_KEY` | `gsk_...` |
| `PIXABAY_API_KEY` | `12345678-...` |
| `PEXELS_API_KEY` | `abcdef...` |
| `TELEGRAM_BOT_TOKEN` | `bot:...` |
| `TELEGRAM_CHAT_ID` | `987654321` |
| `BURC_BATCH_TIME` | `06:00` |
| `TIMEZONE` | `Europe/Istanbul` |

**YouTube credentials** — bu önemli ve biraz teknik:

Lokal bilgisayarında şu komutu çalıştır:

```bash
python -c "import base64; print('CREDENTIALS_BURC=' + base64.b64encode(open('credentials_burc.json','rb').read()).decode())"
python -c "import base64; print('TOKEN_BURC=' + base64.b64encode(open('token_burc.json','rb').read()).decode())"
```

Çıkan iki uzun string'i Railway Variables'a ekle:
- `CREDENTIALS_BURC` = (base64 çıktısı)
- `TOKEN_BURC` = (base64 çıktısı)

Uygulama başlarken `bootstrap.py` bunları dosyaya dönüştürür.

### Adım 4: Deploy ve test

Railway otomatik redeploy eder. 1-2 dakika içinde "Live" olur.

Sağ üstte Railway'in verdiği URL'ye gir: `https://burc-agent-production-xxxx.up.railway.app`

Web paneli açılır, burçlara tıklayıp üretim yapabilirsin.

Telegram bot da otomatik çalışır — `/yardim` yaz.

### Adım 5: Mevcut verileri kontrol

İlk deploy başarılıysa:
- `/health` endpoint'i `{"status":"ok"}` döner
- Web paneli açılır
- Telegram'a "Burç Agent aktif!" mesajı düşer

Bundan sonra her gün 06:00'da (Europe/Istanbul) 12 burç otomatik yayınlanır.

## Telegram Komutları

```
/burc koç          Tek burç için üret + yükle
/burc aslan
/burc balık
/tumburclar        12 burcu sırayla üret (~30-60 dk)
/durum             Çalışan işlem var mı?
/iptal             Toplu üretimi durdur
/yardim            Bu mesaj
```

Türkçe aksanlı (koç), aksansız (koc), büyük harf (KOC), İngilizce (aries) — hepsi çalışır.

## Web API

```
GET  /api/signs               → 12 burç meta bilgisi
POST /api/produce/<burç>      → Tek burç için üretim başlat
POST /api/produce-all         → 12 burç için batch
GET  /api/jobs                → Çalışan işlerin durumu
GET  /api/history             → Son 50 yayın
GET  /health                  → Sağlık kontrolü
```

## Maliyet

- **Railway:** Aylık 500 saat ücretsiz (uyku modu var, yeterli)
- **Anthropic (Claude Haiku 4.5):** Günde 12 burç × ~500 token = ~$0.05/gün, aylık ~$1.50
- **Gemini:** Ücretsiz (günlük 1500 istek limiti)
- **Groq:** Ücretsiz
- **Pixabay/Pexels:** Ücretsiz
- **gTTS:** Ücretsiz
- **ElevenLabs (opsiyonel):** Ücretsiz tier'da ayda 10k karakter yeter
- **YouTube Data API:** Ücretsiz (günlük 10.000 quota; her upload ~1.600 quota → günde 6 video. Daha fazlası için [quota artışı başvur](https://support.google.com/youtube/contact/yt_api_form))

**Toplam aylık tahmin:** ~$2-3 (sadece Anthropic için kredi)

## Sorun Giderme

### Video render'da takılıyor
Railway'de Linux var, FFmpeg dahil. Yerel Windows'ta MoviePy bazen sessiz çöker — Railway'e deploy edince bu sorun çözülür.

### "access_denied" YouTube yetkilendirmesinde
Google Cloud Console → OAuth consent screen → Test users'a Gmail'ini ekledin mi? Eklemediysen erişemezsin.

### "quotaExceeded" YouTube upload'da
Günlük 10.000 quota doldu. Ertesi gün resetlenir. Sürekli 12 video yüklemek istiyorsan quota artışı başvurusu yap (ücretsiz, 1-2 hafta).

### Telegram bot cevap vermiyor
`.env`'deki `TELEGRAM_CHAT_ID` yanlış olabilir. `@userinfobot`'a mesaj atıp doğru ID'ni öğren.

### Claude "credit balance too low"
Anthropic Console → Plans & Billing → Add credits ($5 minimum).

## Dosya Yapısı

```
burc_v2/
├── app.py                    Ana Flask uygulaması
├── bootstrap.py              Ortam hazırlığı (env → dosya, logging)
├── pipeline.py               Orchestrator (content → video → upload)
├── scheduler.py              Günlük otomatik cron
├── telegram_bot.py           Telegram bot (long polling)
│
├── services/
│   ├── content.py            Claude/Gemini/Groq fallback
│   ├── images.py             Pixabay + Pexels
│   ├── tts.py                ElevenLabs → Edge → gTTS
│   ├── video.py              MoviePy video render
│   └── youtube.py            YouTube OAuth + upload
│
├── zodiac/
│   └── signs.py              12 burç meta bilgisi
│
├── templates/
│   └── dashboard.html        Web paneli
│
├── static/preview/           Önizleme videoları (gitignored)
├── output/                   Üretilmiş videolar (gitignored)
├── data/                     history.json, used_themes.json
├── shortmusic/               Arka plan müzikleri (opsiyonel)
│
├── requirements.txt          Python bağımlılıkları
├── Dockerfile                Railway build
├── railway.toml              Railway config
├── .env.example              Env template
├── .gitignore
└── README.md
```

## Lisans

Kişisel kullanım için. API anahtarları sana ait, sorumluluğu da sana ait.
