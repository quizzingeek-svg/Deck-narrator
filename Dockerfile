# Deck Narrator Bot: self-contained image (LibreOffice rendering, ffmpeg, poppler, multilingual fonts,
# and a pre-downloaded Whisper model so speech recognition works offline).
FROM python:3.12-slim-bookworm

ARG WHISPER_MODELS="base"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/models/hf \
    HOME=/home/app \
    WHISPER_MODEL=base \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# System deps: LibreOffice Impress only (no recommends = no Java/GUI extras), poppler (pdftoppm), ffmpeg,
# fonts: Noto core (Latin/Greek/Cyrillic/Arabic/Hebrew/Devanagari + other Indic, Thai, Ethiopic, Khmer, Myanmar...),
# Noto CJK (Chinese/Japanese/Korean), metric-compatible Office fonts (Carlito=Calibri, Caladea=Cambria, Liberation=Arial/Times).
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-impress \
      poppler-utils ffmpeg curl ca-certificates fontconfig \
      fonts-noto-core fonts-noto-cjk fonts-noto-ui-core fonts-noto-color-emoji \
      fonts-dejavu-core fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea \
 && fc-cache -f \
 && apt-get clean && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake Whisper model(s) into the image (offline STT). Add "small" for better Indic accuracy:
#   docker build --build-arg WHISPER_MODELS="base small" -t deck-narrator-bot .
RUN mkdir -p /opt/models/hf \
 && for m in $WHISPER_MODELS; do \
      python -c "from faster_whisper import WhisperModel; WhisperModel('$m', device='cpu', compute_type='int8'); print('cached $m')"; \
    done

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin app
COPY --chown=app:app . /app
RUN mkdir -p /app/data/audio_cache /app/data/renders /app/data/uploads \
 && chown -R app:app /app/data /opt/models

USER 1000:1000
EXPOSE 8501
HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=5 \
  CMD ["curl", "-fsS", "http://localhost:8501/_stcore/health"]

CMD ["python", "-m", "streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", "--browser.gatherUsageStats=false", "--server.maxUploadSize=300"]
