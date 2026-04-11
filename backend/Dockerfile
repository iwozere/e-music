FROM python:3.11-slim

WORKDIR /app

# ffmpeg + Deno: yt-dlp needs a JS runtime + EJS scripts for YouTube challenge solving
# (see https://github.com/yt-dlp/yt-dlp/wiki/EJS). PyPI installs scripts via yt-dlp[default].
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

ENV DENO_INSTALL=/usr/local
RUN curl -fsSL https://deno.land/install.sh | sh \
    && deno --version

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
