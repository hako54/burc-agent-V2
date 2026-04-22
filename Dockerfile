# Python 3.12 - stable, moviepy/pillow compatible
FROM python:3.12-slim

# FFmpeg, font paketleri ve temel araçlar
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-liberation \
    fonts-dejavu-core \
    fonts-noto-core \
    fonts-noto-color-emoji \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Önce requirements'i kopyala (cache için)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Kod
COPY . .

# Uygulama dizinleri
RUN mkdir -p data output static/preview shortmusic

# Railway PORT'u dinamik atar, varsayılan 8000
ENV PORT=8000
EXPOSE 8000

# Gunicorn ile Flask app çalıştır. Tek worker çünkü bot ve scheduler
# thread'leri app ile birlikte çalışıyor.
CMD gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 1 \
    --threads 4 \
    --timeout 600 \
    --access-logfile - \
    --error-logfile -
