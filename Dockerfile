# Server image: LilyPond is installed here, not on customer devices.
# LilyPond is invoked only as a separate CLI process by musicmaster.core.render.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    MUSICMASTER_HOST=0.0.0.0

WORKDIR /app

# LilyPond provides server-side Jianpu PDF/SVG rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
      lilypond fonts-dejavu-core libsndfile1 libgomp1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir tensorflow==2.15.0 \
    && python -m pip install --no-cache-dir --no-build-isolation --no-deps ./vendor/crepe \
    && if [ -n "$CREPE_MODEL_URL" ]; then CREPE_MODEL_URL="$CREPE_MODEL_URL" python scripts/prepare_crepe_model.py; else python scripts/prepare_crepe_model.py; fi \
    && python -m pip install --no-cache-dir -r requirements/requirements-core.txt \
    && python -m pip install --no-cache-dir -e .

EXPOSE 7860

# Render and other container platforms supply PORT at runtime.
CMD ["sh", "-c", "export MUSICMASTER_PORT=${PORT:-7860}; exec python -m musicmaster.web.server"]
